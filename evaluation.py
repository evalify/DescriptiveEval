"""
This module contains functions to evaluate quiz responses in bulk using LLMs and cache the results.
Functions:
1. get_guidelines - Get the guidelines for a question using an LLM (cached)
2. get_quiz_responses - Get all responses for a quiz based on the quiz ID from the Cockroach database (cached)
3. get_all_questions - Get all questions for a quiz from MongoDB (cached)
4. bulk_evaluate_quiz_responses - Evaluate all responses for a quiz with rubric caching and parallel processing

"""

import os
import json
from dotenv import load_dotenv
import asyncio
from typing import Dict, List
from model import score, LLMProvider, get_llm, generate_guidelines
import itertools
from tqdm import tqdm
from redis import Redis
from utils.misc import DateTimeEncoder
load_dotenv()
CACHE_EX = int(os.getenv('CACHE_EXPIRY', 3600))  # Cache expiry time in seconds


async def get_guidelines(redis_client: Redis, llm, question_id: str, question: str, expected_answer: str,
                         total_score: int):
    """
    Get the guidelines for a question from the cache.
    """
    cached_guidelines = redis_client.get(question_id + '_guidelines_cache')
    if cached_guidelines:
        return json.loads(cached_guidelines)
    guidelines = None
    for i in range(10):
        guidelines = await generate_guidelines(llm, question, expected_answer, total_score)
        if guidelines['guidelines'].startswith("Error:") or guidelines['guidelines'].startswith(
                "Error processing response:"):
            print("Error in generating guidelines. Retrying")
            print("Guidelines:", guidelines)
            continue
        break
    if guidelines is not None:
        redis_client.set(question_id + '_guidelines_cache', json.dumps(guidelines), ex=CACHE_EX)
        print("Guidelines generated for", question_id)
        print(repr(guidelines))
    return guidelines


def get_quiz_responses(cursor, redis_client: Redis, quiz_id: str):
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
      "677cb6bcdee1edc79b6c4333": ["2"],
      question_id : [answer]
        ...
    },
    "violations": "",
    "questionMarks": {
      "677cb6bcdee1edc79b6c4333": 0,
      question_id : marks
        ...
    },
    "totalScore": 45.0,
    "remarks": null
  }
    },...]

    Where, question_id can be matched with the questions retrived from mongo

    :param cursor: PostgresSQL cursor for database operations
    :param redis_client: Redis client for caching
    :param quiz_id: The ID of the quiz to retrieve responses for
    """
    cached_responses = redis_client.get(quiz_id + '_responses_evalcache')
    if cached_responses:
        return json.loads(cached_responses)

    query = """
        SELECT * FROM "QuizResult" WHERE "quizId" = %s;
    """
    cursor.execute(query, (quiz_id,))
    quiz_responses = cursor.fetchall()

    for response in quiz_responses:
        response['id'] = str(response['id'])
        response['submittedAt'] = str(response['submittedAt'])

    redis_client.set(f'{quiz_id}_responses_evalcache', json.dumps(quiz_responses), ex=CACHE_EX)
    return quiz_responses


def get_all_questions(mongo_db, redis_client: Redis, quiz_id: str):
    """
    Get all questions for a quiz from MongoDB
    :param mongo_db: The MongoDB database object i.e, client[db]
    :param redis_client: Redis client for caching
    :param quiz_id: The ID of the quiz to retrieve questions for
    """
    cached_questions = redis_client.get(quiz_id + '_questions_evalcache')
    if cached_questions:
        return json.loads(cached_questions)

    collection = mongo_db['NEW_QUESTIONS']
    query = {"quizId": quiz_id}
    questions = list(collection.find(query))

    for question in questions:
        question['_id'] = str(question['_id'])

    redis_client.set(f'{quiz_id}_questions_evalcache', json.dumps(questions, cls=DateTimeEncoder), ex=CACHE_EX)
    return questions


async def bulk_evaluate_quiz_responses(quiz_id: str, pg_cursor, pg_conn, mongo_db, redis_client: Redis): #TODO: Handle Errors
    """
    Evaluate all responses for a quiz with rubric caching and parallel processing.

    :param quiz_id: The ID of the quiz to evaluate
    :param pg_cursor: PostgresSQL cursor from database.get_postgres_cursor() - for getting quiz responses
    :param pg_conn: PostgresSQL connection from database.get_postgres_cursor() - for updating the database with results
    :param mongo_db: MongoDB database from database.get_mongo_client() - for getting questions
    :param redis_client: Redis client from database.get_redis_client() - for caching
    """
    quiz_responses = get_quiz_responses(cursor=pg_cursor, redis_client=redis_client, quiz_id=quiz_id)
    questions = get_all_questions(mongo_db=mongo_db, redis_client=redis_client, quiz_id=quiz_id)

    keys = [os.getenv("GROQ_API_KEY3"), os.getenv("GROQ_API_KEY2"), os.getenv("GROQ_API_KEY4"),
            os.getenv("GROQ_API_KEY"), os.getenv("GROQ_API_KEY5")]
    groq_api_keys = itertools.cycle(keys)

    for i, key in enumerate(keys, start=1):
        print(f"Key {i}: {key}")

    subset_quiz_responses = quiz_responses

    for quiz_result in tqdm(subset_quiz_responses, desc="Evaluating quiz responses"):
        if quiz_result["remarks"] is None:
            quiz_result["remarks"] = {}
        for question in questions:
            qid = str(question["_id"])
            """
            if question.get("type", "").upper() == "MCQ":
                if qid in quiz_result["responses"]:
                    student_answers = quiz_result["responses"][qid]
                    correct_answers = question["answer"]
                    if set(student_answers) == set(correct_answers):
                        mcq_score = question.get("marks", 1)
                    else:
                        mcq_score = 0
                    quiz_result["questionMarks"].update({qid: mcq_score})
            """

            if question.get("type", "").upper() == "DESCRIPTIVE":
                if qid in quiz_result[
                    "responses"]:  # and qid not in quiz_result["remarks"] and quiz_result["remarks"] is not None:
                    student_answers = quiz_result["responses"][qid]
                    current_llm = get_llm(LLMProvider.GROQ, next(groq_api_keys, None))
                    # TODO: Restore -env question_guidelines = await question.get("guidelines", get_guidelines(qid, current_llm, question["question"], question["explanation"], question.get("marks", 10)))
                    question_guidelines = question["guidelines"]
                    score_res = await score(
                        llm=current_llm,
                        question=question["question"],
                        student_ans=" ".join(student_answers),
                        expected_ans=" ".join(question["explanation"]),
                        total_score=question.get("marks", 10),
                        guidelines=question_guidelines
                    )

                    # Catch silent errors
                    for i in range(10):
                        if score_res["breakdown"].startswith("Error:") and score_res['rubric'].startswith("Error:"):
                            # Retry with the next API key
                            print("Encountered Error. Retrying with a different API key with i=", i)
                            if i < 5:
                                current_llm = get_llm(LLMProvider.GROQ, next(groq_api_keys))
                            else:
                                print("All API keys for SpecDec exhausted. Checking for Versatile")
                                current_llm = get_llm(LLMProvider.GROQ, next(groq_api_keys, 'llama-3.3-70b-versatile'))

                            score_res = await score(
                                llm=current_llm,
                                question=question["question"],
                                student_ans=" ".join(student_answers),
                                expected_ans=" ".join(question["explanation"]),
                                total_score=question.get("marks", 10),
                                guidelines=question["guidelines"]
                            )
                        else:
                            break
                    else:
                        if score_res["breakdown"].startswith("Error:") and score_res['rubric'].startswith("Error:"):
                            raise Exception("Failed to evaluate the response. All API keys exhausted.")

                    student_score = score_res["score"]
                    reason = score_res["reason"]
                    rubrics = score_res["rubric"]
                    breakdown = score_res["breakdown"]

                    quiz_result["questionMarks"].update({qid: student_score})
                    quiz_result["remarks"][qid] = f"### Reason:\n{reason}\n\n{breakdown}{rubrics}\n\n"
            quiz_result["score"] = sum(quiz_result["questionMarks"].values())
            try:
                with open('data/json/quiz_responses_evaluated_LA.json', 'w') as f:
                    json.dump(subset_quiz_responses, f, indent=4)
            except IOError as e:
                print(f"Error writing to file: {e}")

    # Save results back to database
    # for result in quiz_responses:
    #     pg_cursor.execute(
    #         """UPDATE "QuizResult" 
    #            SET "score" = %s, "remarks" = %s, "questionMarks" = %s 
    #            WHERE "id" = %s""",
    #         (result["score"], json.dumps(result["remarks"]), 
    #          json.dumps(result["questionMarks"]), result["id"])
    #     )
    # pg_conn.commit()

    return quiz_responses #TODO: Update return message to be more meaningful


if __name__ == "__main__":
    from datetime import datetime
    

    from database import get_postgres_cursor, get_mongo_client, get_redis_client

    my_pg_cursor, my_pg_conn = get_postgres_cursor()
    my_mongo_db = get_mongo_client()
    my_redis_client = get_redis_client()

    my_quiz_id = "cm64n3edl0006xyrxnp4llbe4"
    # asyncio.run(bulk_evaluate_quiz_responses(
    #     quiz_id=my_quiz_id,
    #     pg_cursor=my_pg_cursor,
    #     pg_conn=my_pg_conn,
    #     mongo_db=my_mongo_db,
    #     redis_client=my_redis_client)
    # )
    
    # Get quiz results
    # results = get_quiz_responses(my_pg_cursor, my_redis_client, my_quiz_id)
    # with open('data/json/quiz_responses_quiz3.json', 'w') as f:
    #     json.dump(results, f, indent=4)
    # Get all questions
    questions = get_all_questions(my_mongo_db, my_redis_client, my_quiz_id)
    with open('data/json/quiz_questions_quiz3.json', 'w') as f:
        json.dump(questions, f, indent=4, cls=DateTimeEncoder)
