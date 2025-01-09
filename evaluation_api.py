import os
import psycopg2
import json
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import asyncio
from typing import Dict, List
from model import score, LLMProvider, get_llm
from pymongo import MongoClient
import redis
import itertools
from tqdm import tqdm
load_dotenv()
redis_client = redis.StrictRedis(host='172.17.9.74', port=32768, db=2, decode_responses=True)

def get_quiz_responses(database_url, quiz_id):
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
    },..]


    Where, question_id can be matched with the questions retrived from mongo
    :param database_url: The URL for the database connection.
    :param quiz_id: The ID of the quiz to retrieve responses for.
    """
    if 'pool_max' in database_url:
        database_url = database_url.replace('&pool_max=50', '')
    
    connection = psycopg2.connect(database_url)
    cursor = connection.cursor(cursor_factory=RealDictCursor)

    query = """
        SELECT * FROM "QuizResult" WHERE "quizId" = '{}';
    """.format(quiz_id)
    
    cursor.execute(query)
    quiz_responses = cursor.fetchall()

    for response in quiz_responses:
        response['id'] = str(response['id'])
        response['submittedAt'] = str(response['submittedAt'])

    cursor.close()
    connection.close()

    return quiz_responses

def get_all_questions(quiz_id:str):
    """
    Get all questions for a quiz based on the quiz ID from the MongoDB database.
    """
    client = MongoClient(os.getenv("MONGODB_URI"))
    
    db = client["Evalify"]
    collection = db['NEW_QUESTIONS']
    
    query = {"quizId": quiz_id}
    cache = redis.get(quiz_id+'eval_cache')
    if cache:
        return cache
    
    new_questions = list(collection.find(query))
    
    for question in new_questions:
        question['_id'] = str(question['_id'])

    redis.set(quiz_id+'eval_cache', new_questions, ex=3600)
    return new_questions


async def bulk_evaluate_quiz_responses(database_url: str, quiz_id: str):
    """
    Evaluate all responses for a quiz with rubric caching and parallel processing.
    """
    # quiz_responses = get_quiz_responses(database_url, quiz_id)
    # questions = get_all_questions(quiz_id)

    with open('quiz_responses.json', 'r') as f:
        quiz_responses = json.load(f)

    with open('mongo_questions.json', 'r') as f:
        questions = json.load(f)

    keys = [os.getenv("GROQ_API_KEY"), os.getenv("GROQ_API_KEY2"), os.getenv("GROQ_API_KEY3"), os.getenv("GROQ_API_KEY4"), os.getenv("GROQ_API_KEY5")]
    groq_api_keys = itertools.cycle(keys)
    
    for key in keys:
        print(key)

    current_llm = get_llm(LLMProvider.GROQ,next(groq_api_keys,None))

    for quiz_result in tqdm(quiz_responses, desc="Evaluating quiz responses"):
        quiz_result["remarks"] = {}
        for question in questions:
            qid = str(question["_id"])

            if question.get("type", "").upper() == "MCQ":
                if qid in quiz_result["responses"]:
                    student_answers = quiz_result["responses"][qid]
                    correct_answers = question["answer"]
                    if set(student_answers) == set(correct_answers):
                        mcq_score = question.get("marks", 1)
                    else:
                        mcq_score = 0
                    quiz_result["questionMarks"].update({qid: mcq_score})


            if question.get("type", "").upper() == "DESCRIPTIVE":
                if qid in quiz_result["responses"]:
                    student_answers = quiz_result["responses"][qid]
                    score_res = await score(
                        llm=current_llm,
                        question=question["question"],
                        student_ans=" ".join(student_answers),
                        expected_ans=" ".join(question["explanation"]),
                        total_score= 10 #question.get("marks", 10)
                    )

                    # Catch silent errors
                    for i in range(10):
                        if score_res["breakdown"].startswith("Error:") and score_res['rubric'].startswith("Error:"):
                            # Retry with the next API key
                            if i<5:
                                current_llm = get_llm(LLMProvider.GROQ,next(groq_api_keys))
                            else:
                                current_llm = get_llm(LLMProvider.GROQ,next(groq_api_keys,'llama-3.3-70b-versatile'))
                                
                            score_res = await score(
                                llm=current_llm,
                                question=question["question"],
                                student_ans=" ".join(student_answers),
                                expected_ans=" ".join(question["explanation"]),
                                total_score= 10 #question.get("marks", 10)
                            )
                        else:
                            break
                    else:
                        if score_res["breakdown"].startswith("Error:") and score_res['rubric'].startswith("Error:"):
                            raise Exception("Failed to evaluate the response")

                    student_score = score_res["score"]
                    reason = score_res["reason"]
                    rubrics = score_res["rubric"]
                    breakdown = score_res["breakdown"]

                    quiz_result["questionMarks"].update({qid: student_score})
                    quiz_result["remarks"][qid] = f"###Reason:\n{reason}###Rubrics:\n{rubrics}###Score Breakdown\n{breakdown}"
        quiz_result["score"] = sum(quiz_result["questionMarks"].values())
        with open('quiz_responses_evaluated.json', 'w') as f:
            json.dump(quiz_responses, f, indent=4)

if __name__ == "__main__":
    database_url = os.getenv('COCKROACH_DB')
    quiz_id = "quizid123"
    # results = get_quiz_responses(database_url, quiz_id)
    # with open('quiz_responses.json', 'w') as f:
    #     json.dump(results, f, indent=4)
    asyncio.run(bulk_evaluate_quiz_responses(database_url, quiz_id))