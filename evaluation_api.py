import os
import psycopg2
import json
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import asyncio
from typing import Dict, List
from model import score, llm
from pymongo import MongoClient

load_dotenv()

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

def get_all_questions(quiz_id):
    """
    Get all questions for a quiz based on the quiz ID from the MongoDB database.
    """
    client = MongoClient(os.getenv("MONGODB_URI"))
    
    db = client["Evalify"]
    collection = db['NEW_QUESTIONS']
    
    query = {"quizId": quiz_id}
    new_questions = list(collection.find(query))
    
    for question in new_questions:
        question['_id'] = str(question['_id'])

    return new_questions


async def bulk_evaluate_quiz_responses(database_url: str, quiz_id: str):
    """
    Evaluate all responses for a quiz with rubric caching and parallel processing.
    """
    quiz_responses = get_quiz_responses(database_url, quiz_id)
    questions = get_all_questions(quiz_id)
    for quiz_result in quiz_responses:
        quiz_result["remarks"] = {}
        for question in questions:
            qid = str(question["_id"])
            if qid in quiz_result["responses"]:
                student_answers = quiz_result["responses"][qid]
                score_res = await score(
                    llm=llm,
                    student_ans=" ".join(student_answers),
                    expected_ans=" ".join(question["answer"]),
                    total_score=question["marks"] if "marks" in question else 1
                )
                rubrics = score_res["rubric"]
                breakdown = score_res["breakdown"]
                quiz_result["remarks"][qid] = f"{rubrics}\n{breakdown}"

    with open('quiz_responses.json', 'w') as f:
        json.dump(quiz_responses, f, indent=4)

if __name__ == "__main__":
    database_url = os.getenv('COCKROACH_DB')
    quiz_id = "quizid123"
    results = get_quiz_responses(database_url, quiz_id)
    with open('quiz_responses.json', 'w') as f:
        json.dump(results, f, indent=4)