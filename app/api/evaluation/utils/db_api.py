"""
This module provides abstract functions for interacting with CockroachDB/Mongo/Redis database services.
"""

import asyncio
import json
import time
from typing import Dict, Any, Optional
import psycopg2
from psycopg2.errors import QueryCanceledError
from dotenv import load_dotenv
from redis import Redis

# Custom imports
from app.api.scoring.service import generate_guidelines
from app.core.logger import logger
from app.utils.misc import DateTimeEncoder, save_quiz_data
from app.config.constants import CACHE_EX, DB_MAX_RETRIES
from app.database.postgres import get_db_connection_no_context

load_dotenv()


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

    try:
        guidelines = await generate_guidelines(
            llm, question, expected_answer, total_score, errors
        )
    except Exception as e:
        error_msg = f"Unexpected error generating guidelines: {str(e)}"
        errors.append(error_msg)

    if guidelines is None or int(guidelines.get("status", 403)) == 403:
        error_details = "\n".join(errors)
        logger.error(
            f"Failed to generate guidelines for question {question_id}"
            f"Errors encountered:\n{error_details}\n"
            f"Guidelines response: {guidelines if guidelines else 'None'}"
        )
        # FIXME: Temporary error override
        # raise LLMEvaluationError(
        # f"Failed to generate guidelines after {MAX_RETRIES} attempts.\nErrors encountered:\n{error_details}")
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


def get_quiz_responses(
    cursor, redis_client: Redis, quiz_id: str, save_to_file=True, override_cache=False
):
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
    if not override_cache:
        cached_responses = redis_client.get(f"responses:{quiz_id}_responses_evalcache")
        if cached_responses:
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
        save_quiz_data(
            quiz_responses, quiz_id, f"responses_{time.strftime('%Y%m%d_%H%M%S')}"
        )
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
    max_retries = DB_MAX_RETRIES

    new_cursor = False
    while retries < max_retries:
        try:
            if retries == max_retries - 1:
                # At last retry, get a new connection
                logger.warning(
                    f"Retrying to get a new connection for response {response['id']} (attempt {retries + 1})"
                )
                cursor, conn = get_db_connection_no_context()
                new_cursor = True

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

            if new_cursor:
                # Close the new cursor if it was created
                cursor.close()
                conn.close()

            return

        except (asyncio.TimeoutError, QueryCanceledError):
            retries += 1
            logger.warning(
                f"Operation timed out/cancelled for response {response['id']} (attempt {retries}/{max_retries})"
            )
            if retries == max_retries:
                logger.error(
                    f"Max retries reached for updating response {response['id']}"
                )
                raise
            wait_time = 2**retries
            await asyncio.sleep(wait_time)

        # Errors that require a new connection but not backoff
        # This includes cursor closed errors
        except (psycopg2.InterfaceError, psycopg2.ProgrammingError):
            # Cursor is closed, get a new connection
            logger.warning(
                f"Cursor closed for response {response['id']} (attempt {retries + 1})"
            )
            cursor, conn = get_db_connection_no_context()
            new_cursor = True
            retries += 1
            if retries == max_retries:
                logger.error(
                    f"Max retries reached for updating response {response['id']}",
                    exc_info=True,
                )
                raise

        # For operational/database errors - add backoff
        except (psycopg2.OperationalError, psycopg2.DatabaseError) as e:
            retries += 1
            logger.error(
                f"Op/Db Error for response {response['id']}: {str(e)} - retry {retries}/{max_retries}"
            )
            if retries == max_retries:
                logger.error(
                    f"Max retries reached for updating response {response['id']}"
                )
                raise
            wait_time = 2**retries  # Add exponential backoff for these errors
            await asyncio.sleep(wait_time)

        except Exception as e:
            retries += 1
            logger.error(
                f"Error updating response {response['id']}: {str(e)} - retry {retries}/{max_retries}"
            )
            if retries == max_retries:
                logger.error(
                    f"Max retries reached for updating response {response['id']}"
                )
                raise
            wait_time = 1  # Add a fixed wait time for other errors
            await asyncio.sleep(wait_time)

        finally:
            # Ensure connection is in a clean state
            try:
                if conn.status != psycopg2.extensions.STATUS_READY:
                    conn.rollback()
            except Exception:
                pass


def get_all_questions(
    mongo_db, redis_client: Redis, quiz_id: str, save_to_file=True, override_cache=False
):
    """
    Get all questions for a quiz from MongoDB
    :param mongo_db: The MongoDB database object i.e, client[db]
    :param redis_client: Redis client for caching
    :param quiz_id: The ID of the quiz to retrieve questions for
    :param save_to_file: Save the questions to a file (default: True)
    :param override_cache: Override the cache if set to True (default: False)
    """
    if not override_cache:
        cached_questions = redis_client.get(f"questions:{quiz_id}_questions_evalcache")
        if cached_questions:
            # Cache hit, return cached questions
            print("Questions Cache hit!")
            save_quiz_data(json.loads(cached_questions), quiz_id, "questions")
            return json.loads(cached_questions)

    collection = mongo_db["NEW_QUESTIONS"]
    query = {"quizId": quiz_id}
    questions = list(collection.find(query))

    for question in questions:
        question["_id"] = str(question["_id"])

    if save_to_file:
        save_quiz_data(
            questions, quiz_id, f"questions_{time.strftime('%Y%m%d_%H%M%S')}"
        )

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


def get_quiz_isevaluated(
    cursor,
    quiz_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Get the evaluation status for
    a quiz from the Cockroach database.
    """
    query = """
       SELECT "isEvaluated" FROM "Quiz" WHERE "id" = %s;
    """
    cursor.execute(query, (quiz_id,))
    return cursor.fetchone()
