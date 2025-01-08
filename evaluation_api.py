import os
import psycopg2
import json
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import asyncio
from typing import Dict, List
from model import score, llm

load_dotenv()

def get_quiz_responses(database_url, quiz_id):
    """
    Get all responses for a quiz based on the quiz ID from the database.

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

if __name__ == "__main__":
    database_url = os.getenv('DATABASE_URL')
    quiz_id = "quizid123"
    results = get_quiz_responses(database_url, quiz_id)
    with open('quiz_responses.json', 'w') as f:
        json.dump(results, f, indent=4)