"""
This module provides abstract functions for interacting with CockroachDB/Mongo/Redis database services.
"""

import asyncio
import json
import os
from typing import Dict, Any, Optional
import psycopg2
from psycopg2.errors import QueryCanceledError
from dotenv import load_dotenv
from redis import Redis

# Custom imports
from model import generate_guidelines
from utils.logger import logger
from utils.misc import DateTimeEncoder, save_quiz_data

load_dotenv()
CACHE_EX = int(os.getenv("CACHE_EX", 3600))  # Cache expiry time in seconds
MAX_RETRIES = int(
    os.getenv("MAX_RETRIES", 10)
)  # Maximum number of retries for LLM evaluation


async def get_guidelines(
    redis_client: Redis,
    llm,
    question_id: str,
    question: str,
    expected_answer: str,
    total_score: int,
):
    """Get the guidelines for a question from the cache."""
    cached_guidelines = redis_client.get(f"guidelines:{question_id}_guidelines_cache")
    if cached_guidelines:
        return json.loads(cached_guidelines)

    guidelines = None
    errors = []

    for attempt in range(MAX_RETRIES):
        try:
            guidelines = await generate_guidelines(
                llm, question, expected_answer, total_score, errors
            )
            if (
                guidelines["guidelines"].startswith(
                    ("Error:", "Error processing response:")
                )
                or guidelines["status"] == 403
            ):
                error_msg = guidelines.get("error")
                logger.warning(
                    f"Attempt {attempt + 1}/{MAX_RETRIES}: Failed to generate guidelines for question {question_id}: {error_msg}"
                )
                errors.append(error_msg)
                continue
            break
        except Exception as e:
            error_msg = f"Unexpected error generating guidelines: {str(e)}"
            logger.warning(f"Attempt {attempt + 1}/{MAX_RETRIES}: {error_msg}")
            errors.append(error_msg)

    if guidelines is None or int(guidelines.get("status", 403)) == 403:
        error_details = "\n".join(errors)
        logger.error(
            f"Failed to generate guidelines for question {question_id} after {MAX_RETRIES} attempts.\n"
            f"Errors encountered:\n{error_details}\n"
            f"Guidelines response: {guidelines if guidelines else 'None'}"
        )
        # FIXME: Temporary error override
        # raise LLMEvaluationError(
        # f"Failed to generate guidelines after {MAX_RETRIES} attempts.\nErrors encountered:\n{error_details}")
        logger.warning(
            f"Failed to generate guidelines for question {question_id} after {MAX_RETRIES} attempts.\n"
        )
    else:
        redis_client.set(
            f"guidelines:{question_id}_guidelines_cache",
            json.dumps(guidelines),
            ex=86400,
        )
        logger.info(
            f"Successfully generated and cached guidelines for question {question_id}"
        )
    return guidelines


def get_quiz_responses(cursor, redis_client: Redis, quiz_id: str, save_to_file=True, override_cache=False):
    """
      Get all responses for a quiz based on the quiz ID from the Cockroach database.
      
      QuizResult Schema:
      [{

      "id": "cm5mbro5700br8pe36z0wh8ko",
      "studentId": "cm4tnp0o000b9dji9djqsjvfw",
      "quizId": "cm5ly4fgu00b28pe3sx17kiur",
      "score": 16.0,
      "submittedAt": "2025-01-07 10:25:44.442000",
      "responses": {
          question_id: {          # Updated Schema
              student_answer,
              remarks,
              score,
              breakdown
          }
          ...
      },
      "violations": "",
      "totalScore": 45.0,
    }
      },...]

      Where, question_id can be matched with the questions retrieved from mongo

      :param cursor: PostgresSQL cursor for database operations
      :param redis_client: Redis client for caching
      :param quiz_id: The ID of the quiz to retrieve responses for
      :param save_to_file: Save the responses to a file (default: True)
      :param override_cache: Override the cache and fetch fresh data (default: False)
    """
    cached_responses = redis_client.get(f"responses:{quiz_id}_responses_evalcache")
    if cached_responses and not override_cache:
        print("Responses Cache hit!")
        save_quiz_data(json.loads(cached_responses), quiz_id, "responses")
        return json.loads(cached_responses)

    query = """
        SELECT * FROM "QuizResult" WHERE "quizId" = %s AND "isSubmitted"=true;
    """
    cursor.execute(query, (quiz_id,))
    quiz_responses = cursor.fetchall()

    for response in quiz_responses:
        response["id"] = str(response["id"])
        response["submittedAt"] = str(response["submittedAt"])

    redis_client.set(
        f"responses:{quiz_id}_responses_evalcache",
        json.dumps(quiz_responses, cls=DateTimeEncoder),
        ex=CACHE_EX,
    )

    if save_to_file:
        save_quiz_data(quiz_responses, quiz_id, "responses")
    return quiz_responses


async def set_quiz_responses(redis_client: Redis, quiz_id: str, responses: dict):
    """
    Update the cache with the evaluated results, using async thread.

    :param redis_client: Redis client for caching
    :param quiz_id: The ID of the quiz to update responses for
    :param responses: The evaluated responses to update in the cache
    """
    await asyncio.to_thread(
        redis_client.set,
        f"responses:{quiz_id}_responses_evalcache",
        json.dumps(responses, cls=DateTimeEncoder),
        ex=CACHE_EX,
    )


async def set_quiz_response(cursor, conn, response: dict):
    """Update database with evaluated results with proper timeout handling"""
    timeout = 30  # seconds
    retries = 0
    max_retries = int(os.getenv("DB_MAX_RETRIES", 3))

    while retries < max_retries:
        try:
            # Set statement timeout at session level
            cursor.execute("SET LOCAL statement_timeout = %s", (timeout * 1000,))

            async with asyncio.timeout(timeout):
                cursor.execute(
                    """UPDATE "QuizResult" 
                       SET "responses" = %s::jsonb, 
                           "score" = %s, 
                           "totalScore" = %s, 
                           "isEvaluated" = 'EVALUATED'
                       WHERE "id" = %s""",
                    (
                        json.dumps(response["responses"]),
                        response["score"],
                        response["totalScore"],
                        response["id"],
                    ),
                )
                conn.commit()

            logger.info(f"Successfully updated response {response['id']}")
            return

        except (asyncio.TimeoutError, QueryCanceledError) as e:
            retries += 1
            logger.warning(
                f"Operation timed out/cancelled for response {response['id']} (attempt {retries}/{max_retries})"
            )
            if retries == max_retries:
                raise
            wait_time = 2**retries
            await asyncio.sleep(wait_time)

        except Exception as e:
            retries += 1
            logger.error(f"Error updating response {response['id']}: {str(e)}")
            if retries == max_retries:
                raise
            wait_time = 2**retries
            await asyncio.sleep(wait_time)

        finally:
            # Ensure connection is in a clean state
            try:
                if conn.status != psycopg2.extensions.STATUS_READY:
                    conn.rollback()
            except Exception:
                pass


def get_all_questions(mongo_db, redis_client: Redis, quiz_id: str, save_to_file=True, override_cache=False):
    """
    Get all questions for a quiz from MongoDB
    :param mongo_db: The MongoDB database object i.e, client[db]
    :param save_to_file: Save the questions to a file (default: True)
    :param override_cache: Override the cache if set to True (default: False)
    :param quiz_id: The ID of the quiz to retrieve questions for
    :param save_to_file: Save the questions to a file (default: True)
    :param save_to_file: Save the questions to a file (default: True)
    """
    cached_questions = redis_client.get(f"questions:{quiz_id}_questions_evalcache")
    if cached_questions and not override_cache:
        print("Questions Cache hit!")
        save_quiz_data(json.loads(cached_questions), quiz_id, "questions")
        return json.loads(cached_questions)

    collection = mongo_db["NEW_QUESTIONS"]
    query = {"quizId": quiz_id}
    questions = list(collection.find(query))

    for question in questions:
        question["_id"] = str(question["_id"])

    if save_to_file:
        save_quiz_data(questions, quiz_id, "questions")

    redis_client.set(
        f"questions:{quiz_id}_questions_evalcache",
        json.dumps(questions, cls=DateTimeEncoder),
        ex=CACHE_EX,
    )

    return questions


def get_evaluation_settings(cursor, quiz_id: str) -> Optional[Dict[str, Any]]:
    """
    Get the evaluation settings for a quiz from the Cockroach database.
    """
    query = """
       SELECT * FROM "EvaluationSettings" WHERE "quizId" = %s;
    """
    cursor.execute(query, (quiz_id,))
    return cursor.fetchone()
