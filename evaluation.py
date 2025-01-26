"""
This module contains functions to evaluate quiz responses in bulk using LLMs and cache the results.
Functions:
1. get_guidelines - Get the guidelines for a question using an LLM (cached)
2. get_quiz_responses - Get all responses for a quiz based on the quiz ID from the Cockroach database (cached)
3. get_all_questions - Get all questions for a quiz from MongoDB (cached)
4. bulk_evaluate_quiz_responses - Evaluate all responses for a quiz with rubric caching and parallel processing

"""

import asyncio
import itertools
import json
import os

from dotenv import load_dotenv
from redis import Redis
from tqdm import tqdm

from model import score, LLMProvider, get_llm, generate_guidelines
from utils.code_eval import evaluate_coding_question
from utils.misc import DateTimeEncoder, remove_html_tags
from utils.schema_utils import QuizResponseSchema
from utils.static_eval import evaluate_mcq, evaluate_mcq_with_partial_marking, evaluate_true_false, direct_match
from utils.quiz_report import generate_quiz_report, save_quiz_report
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
    for _ in range(10):
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


def get_quiz_responses(cursor, redis_client: Redis, quiz_id: str, save_to_file=True):
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

    Where, question_id can be matched with the questions retrived from mongo

    :param cursor: PostgresSQL cursor for database operations
    :param redis_client: Redis client for caching
    :param quiz_id: The ID of the quiz to retrieve responses for
    :param save_to_file: Save the responses to a file (default: True)
    """
    cached_responses = redis_client.get(quiz_id + '_responses_evalcache')
    if cached_responses:
        print("Responses Cache hit!")
        return json.loads(cached_responses)

    query = """
        SELECT * FROM "QuizResult" WHERE "quizId" = %s;
    """
    cursor.execute(query, (quiz_id,))
    quiz_responses = cursor.fetchall()

    for response in quiz_responses:
        response['id'] = str(response['id'])
        response['submittedAt'] = str(response['submittedAt'])

    redis_client.set(f'{quiz_id}_responses_evalcache', json.dumps(quiz_responses, cls=DateTimeEncoder), ex=CACHE_EX)

    if save_to_file:
        try:
            with open(f'data/json/{quiz_id}_quiz_responses.json', 'w') as f:
                json.dump(quiz_responses, f, indent=4, cls=DateTimeEncoder)
        except IOError as e:
            print(f"Error writing to file: {e}")

    return quiz_responses

async def set_quiz_response(cursor,conn, response: dict):
    await asyncio.to_thread(
        cursor.execute,
        """UPDATE "QuizResult" 
           SET "responses" = %s, "score" = %s, "totalScore" = %s, "isEvaluated" = 'EVALUATED'
           WHERE "id" = %s""",
        (json.dumps(response["responses"]), response["score"], response["totalScore"], response["id"])
    )
    await asyncio.to_thread(conn.commit)

def get_all_questions(mongo_db, redis_client: Redis, quiz_id: str, save_to_file=True):
    """
    Get all questions for a quiz from MongoDB
    :param mongo_db: The MongoDB database object i.e, client[db]
    :param redis_client: Redis client for caching
    :param quiz_id: The ID of the quiz to retrieve questions for
    :param save_to_file: Save the questions to a file (default: True)
    :param save_to_file: Save the questions to a file (default: True)
    """
    cached_questions = redis_client.get(quiz_id + '_questions_evalcache')
    if cached_questions:
        print("Questions Cache hit!")
        return json.loads(cached_questions)

    collection = mongo_db['NEW_QUESTIONS']
    query = {"quizId": quiz_id}
    questions = list(collection.find(query))

    for question in questions:
        question['_id'] = str(question['_id'])

    redis_client.set(f'{quiz_id}_questions_evalcache', json.dumps(questions, cls=DateTimeEncoder), ex=CACHE_EX)

    if save_to_file:
        try:
            with open(f'data/json/{quiz_id}_quiz_questions.json', 'w') as f:
                json.dump(questions, f, indent=4, cls=DateTimeEncoder)
        except IOError as e:
            print(f"Error writing to file: {e}")
    return questions


def get_evaluation_settings(cursor, quiz_id: str) -> dict | None:
    """
    Get the evaluation settings for a quiz from the Cockroach database.
    """
    query = """
       SELECT * FROM "EvaluationSettings" WHERE "quizId" = %s;
    """
    cursor.execute(query, (quiz_id,))
    return cursor.fetchone()


async def bulk_evaluate_quiz_responses(quiz_id: str, pg_cursor, pg_conn, mongo_db,
                                       redis_client: Redis, save_to_file=True):  # TODO: Handle Errors
    """
    Evaluate all responses for a quiz with rubric caching and parallel processing.

    :param quiz_id: The ID of the quiz to evaluate
    :param pg_cursor: PostgresSQL cursor from database.get_postgres_cursor() - for getting quiz responses
    :param pg_conn: PostgresSQL connection from database.get_postgres_cursor() - for updating the database with results
    :param mongo_db: MongoDB database from database.get_mongo_client() - for getting questions
    :param redis_client: Redis client from database.get_redis_client() - for caching
    :param save_to_file: Save the evaluated responses to a file (default: True)
    """
    quiz_responses = get_quiz_responses(cursor=pg_cursor, redis_client=redis_client, quiz_id=quiz_id,
                                        save_to_file=save_to_file)
    questions = get_all_questions(mongo_db=mongo_db, redis_client=redis_client, quiz_id=quiz_id,
                                  save_to_file=save_to_file)

    evaluation_settings = get_evaluation_settings(pg_cursor, quiz_id) or {} #TODO: Moce this to a class instead of a function
    print(f"Settings for quiz {quiz_id}: {evaluation_settings!r}")
    negative_marking = evaluation_settings.get("negativeMark", False)
    mcq_partial_marking = evaluation_settings.get("mcqPartialMark", False)

    keys = [os.getenv("GROQ_API_KEY"), os.getenv("GROQ_API_KEY2"), os.getenv("GROQ_API_KEY3"),
            os.getenv("GROQ_API_KEY4"), os.getenv("GROQ_API_KEY5")]
    groq_api_keys = itertools.cycle([key for key in keys if key is not None])
    for i, key in enumerate(keys, start=1):
        print(f"Key {i}: {key}")

    try:
        for quiz_result in tqdm(quiz_responses, desc="Evaluating quiz responses"):
            quiz_result["totalScore"] = 0
            for question in questions:
                qid = str(question["_id"])

                # Convert old schema to new schema if the response is a list
                if isinstance(quiz_result["responses"].get(qid), list):
                    quiz_result["responses"][qid] = {
                        "student_answer": quiz_result["responses"][qid],
                        # Other parameters are set to None by default
                    }
                    # Drop questionMarks
                    if "questionMarks" in quiz_result:
                        del quiz_result["questionMarks"]
                try:
                    quiz_result["totalScore"] += question["mark"]  # TODO: Is this correct?
                    question_total_score = question["mark"]
                except KeyError:
                    print(f"Question {qid!r} does not have a 'mark' attribute. Skipping")
                    continue

                if qid not in quiz_result["responses"]:
                    # and not (qid not in quiz_result["remarks"] and quiz_result["remarks"] is not None):
                    continue

                match question.get("type", "").upper():
                    case "MCQ":
                        student_answers = QuizResponseSchema.get_attribute(quiz_result, qid, 'student_answer')
                        correct_answers = question["answer"]
                        if mcq_partial_marking:
                            mcq_score = await evaluate_mcq_with_partial_marking(student_answers, correct_answers, question_total_score)
                        else:
                            mcq_score = await evaluate_mcq(student_answers, correct_answers, question_total_score)

                        QuizResponseSchema.set_attribute(quiz_result, qid, 'score', mcq_score)
                        QuizResponseSchema.set_attribute(quiz_result, qid, 'negative_score',
                                                         question.get("negativeMark", -1)
                                                         if negative_marking and mcq_score <= 0
                                                         else 0) #TODO: Partial marking for MCQ

                    case "DESCRIPTIVE":
                        clean_question = remove_html_tags(question['question']).strip()
                        student_answer = QuizResponseSchema.get_attribute(quiz_result, qid, 'student_answer')[0]

                        if await direct_match(student_answer, question["explanation"], strip=True,
                                              case_sensitive=False):
                            score_res = {
                                "score": question_total_score,
                                "reason": "Exact Match",
                                "breakdown": "Exact Match - LLM not used"
                            }
                        else:
                            current_llm = get_llm(LLMProvider.GROQ, next(groq_api_keys, None))
                            question_guidelines = await question.get("guidelines",
                                                                     get_guidelines(redis_client=redis_client,
                                                                                    question_id=qid,
                                                                                    llm=current_llm,
                                                                                    question=clean_question,
                                                                                    expected_answer=question[
                                                                                        "explanation"],
                                                                                    total_score=question_total_score))
                            for i in range(10):  # Catch silent errors
                                score_res = await score(
                                    llm=current_llm,
                                    question=clean_question,
                                    student_ans=student_answer,
                                    # TODO: What the...? Why are we joining the answers?
                                    expected_ans=" ".join(question["explanation"]),
                                    total_score=question_total_score,
                                    guidelines=question_guidelines
                                )

                                if any(score_res[key].startswith("Error:") for key in
                                       ["breakdown", "rubric"]) or score_res is None:
                                    print("Encountered Error. Retrying with a different API key with i=", i)
                                    current_llm = get_llm(LLMProvider.GROQ,
                                                          next(groq_api_keys),
                                                          'llama-3.3-70b-versatile' if i > 5 else None)
                                else:
                                    break
                            else:
                                raise Exception("Failed to evaluate the response. All API keys exhausted.")

                        QuizResponseSchema.set_attribute(quiz_result, qid, 'score', score_res["score"])
                        QuizResponseSchema.set_attribute(quiz_result, qid, 'remarks', score_res['reason'])
                        QuizResponseSchema.set_attribute(quiz_result, qid, 'breakdown', score_res["breakdown"])

                    case "CODING":
                        response = QuizResponseSchema.get_attribute(quiz_result, qid, 'student_answer')[0]
                        driver_code = question["driverCode"]
                        coding_score, _ = await evaluate_coding_question(
                            student_response=response[0],
                            driver_code=driver_code,
                            test_cases_count=len(question.get("testcases"))
                        )
                        QuizResponseSchema.set_attribute(quiz_result, qid, 'score', coding_score)

                    case "TRUE_FALSE":
                        response = QuizResponseSchema.get_attribute(quiz_result, qid, 'student_answer')[0]
                        correct_answer = question["answer"]
                        tf_score = await evaluate_true_false(response, correct_answer, question_total_score)
                        QuizResponseSchema.set_attribute(quiz_result, qid, 'score', tf_score)
                        QuizResponseSchema.set_attribute(quiz_result, qid, 'negative_score',
                                                         question.get("negativeMark", -1)
                                                         if negative_marking and tf_score <= 0
                                                         else 0)

                    case "FILL_IN_THE_BLANK":
                        response = QuizResponseSchema.get_attribute(quiz_result, qid, 'student_answer')[0]
                        correct_answer = question["answer"]
                        if await direct_match(response, correct_answer, strip=True, case_sensitive=False):
                            fitb_score = question_total_score
                        else: 
                            fitb_score = 0 # TODO: Implement LLM Scoring for Fill in the Blanks
                        QuizResponseSchema.set_attribute(quiz_result, qid, 'score', fitb_score)

                    case _:
                        print(f"Question type {question.get('type')=!r} is not found")

            # Calculate total score
            quiz_result["score"] = sum([
                QuizResponseSchema.get_attribute(quiz_result, qid, 'score') + (
                        QuizResponseSchema.get_attribute(quiz_result, qid, 'negative_score') or 0)
                for qid in quiz_result["responses"].keys()])
            
            # Save result back to database
            await set_quiz_response(pg_cursor, pg_conn, quiz_result)
    finally:
        # Get quiz report
        quiz_report = await generate_quiz_report(quiz_id, quiz_responses, questions)
        await save_quiz_report(quiz_id, quiz_report, pg_cursor, pg_conn, save_to_file)
        pg_cursor.execute(
        """UPDATE "Quiz" SET "isEvaluated" = 'EVALUATED' WHERE "id" = %s""",
        (quiz_id,))
        pg_conn.commit()
        if save_to_file:
            try:
                with open(f'data/json/{quiz_id}_quiz_responses_evaluated.json', 'w') as f:
                    json.dump(quiz_responses, f, indent=4, cls=DateTimeEncoder)
            except IOError as e:
                print(f"Error writing to file: {e}")

    return quiz_responses  # TODO: Update return message to be more meaningful


if __name__ == "__main__":
    from utils.database import get_postgres_cursor, get_mongo_client, get_redis_client

    my_pg_cursor, my_pg_conn = get_postgres_cursor()
    my_mongo_db = get_mongo_client()
    my_redis_client = get_redis_client()

    my_quiz_id = "cm65yjwna0006xydnis96mbwm"
    # Evaluate quiz responses
    asyncio.run(bulk_evaluate_quiz_responses(
        quiz_id=my_quiz_id,
        pg_cursor=my_pg_cursor,
        pg_conn=my_pg_conn,
        mongo_db=my_mongo_db,
        redis_client=my_redis_client,
        save_to_file=True)
    )

    # Get quiz results
    # my_results = get_quiz_responses(my_pg_cursor, my_redis_client, my_quiz_id)
    # with open('data/json/quiz_responses_quiz3.json', 'w') as f:
    #     json.dump(my_results, f, indent=4)

    # Get all questions
    # my_questions = get_all_questions(my_mongo_db, my_redis_client, my_quiz_id)
    # with open('data/json/quiz_questions_quiz3.json', 'w') as f:
    #     json.dump(my_questions, f, indent=4, cls=DateTimeEncoder)
