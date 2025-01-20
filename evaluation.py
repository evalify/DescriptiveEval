import os
import psycopg2
import json
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import asyncio
from typing import Dict, List
from model import score, LLMProvider, get_llm, generate_guidelines
from pymongo import MongoClient
import redis
import itertools
from tqdm import tqdm
load_dotenv()
redis_client = redis.StrictRedis(host='172.17.9.74', port=32768, db=2, decode_responses=True)

CACHE_EX = 3600 # Cache expiry time in seconds

async def get_guidelines(llm, question_id:str, question:str, expected_answer:str, total_score:int):
    """
    Get the guidelines for a question from the cache.
    """
    cached_guidelines = redis_client.get(question_id + '_guidelines_cache')
    if cached_guidelines:
        return json.loads(cached_guidelines)
    guidelines = None
    for i in range(10):
        guidelines = await generate_guidelines(llm, question, expected_answer, total_score)
        if guidelines['guidelines'].startswith("Error:") or guidelines['guidelines'].startswith("Error processing response:"):
            print("Error in generating guidelines. Retrying")
            print("Guidelines:",guidelines)
            continue
        break
    if guidelines is not None:
        redis_client.set(question_id+'_guidelines_cache', json.dumps(guidelines), ex=CACHE_EX)
        print("Guidelines generated for", question_id)
        print(repr(guidelines))
    return guidelines

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
    },...]


    Where, question_id can be matched with the questions retrived from mongo
    :param database_url: The URL for the database connection.
    :param quiz_id: The ID of the quiz to retrieve responses for.
    """

    cached_responses = redis_client.get(quiz_id+'_responses_evalcache')
    if cached_responses:
        return json.loads(cached_responses)
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
    redis_client.set(f'{quiz_id}_responses_evalcache', json.dumps(quiz_responses), ex=CACHE_EX)
    return quiz_responses

def get_all_questions(quiz_id:str):
    """
    Get all questions for a quiz based on the quiz ID from the MongoDB database.
    """
    cached_questions = redis_client.get(quiz_id+'_questions_evalcache')
    if cached_questions:
        return json.loads(cached_questions)

    client = MongoClient(os.getenv("MONGODB_URI"))
    
    db = client["Evalify"]
    collection = db['NEW_QUESTIONS']
    
    query = {"quizId": quiz_id}
    questions = list(collection.find(query))
    for question in questions:
        question['_id'] = str(question['_id'])

    redis_client.set(f'{quiz_id}_questions_evalcache', json.dumps(questions), ex=CACHE_EX)
    return questions


async def bulk_evaluate_quiz_responses(database_url: str, quiz_id: str):
    """
    Evaluate all responses for a quiz with rubric caching and parallel processing.
    """
    quiz_responses = get_quiz_responses(database_url, quiz_id)
    questions = get_all_questions(quiz_id)

    # with open('data/json/quiz_responses.json', 'r') as f:
    #     quiz_responses = json.load(f)
    # with open('data/json/mongo_questions.json', 'r') as f:
    #     questions = json.load(f)

    keys = [os.getenv("GROQ_API_KEY3"), os.getenv("GROQ_API_KEY2"), os.getenv("GROQ_API_KEY4"), os.getenv("GROQ_API_KEY"), os.getenv("GROQ_API_KEY5")]
    groq_api_keys = itertools.cycle(keys)
    
    for i,key in enumerate(keys,start=1):
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
                if qid in quiz_result["responses"]: # and qid not in quiz_result["remarks"] and quiz_result["remarks"] is not None:
                    student_answers = quiz_result["responses"][qid]
                    current_llm = get_llm(LLMProvider.GROQ,next(groq_api_keys,None))
                    # TODO: Restore -env question_guidelines = await question.get("guidelines", get_guidelines(qid, current_llm, question["question"], question["explanation"], question.get("marks", 10)))
                    question_guidelines = question["guidelines"]
                    score_res = await score(
                        llm=current_llm,
                        question=question["question"],
                        student_ans=" ".join(student_answers),
                        expected_ans=" ".join(question["explanation"]),
                        total_score= question.get("marks", 10),
                        guidelines = question_guidelines
                    )

                    # Catch silent errors
                    for i in range(10):
                        if score_res["breakdown"].startswith("Error:") and score_res['rubric'].startswith("Error:"):
                            # Retry with the next API key
                            print("Encountered Error. Retrying with a different API key with i=",i)
                            if i<5:
                                current_llm = get_llm(LLMProvider.GROQ,next(groq_api_keys))
                            else:
                                print("All API keys for SpecDec exhausted. Checking for Versatile")
                                current_llm = get_llm(LLMProvider.GROQ,next(groq_api_keys,'llama-3.3-70b-versatile'))
                                
                            score_res = await score(
                                llm=current_llm,
                                question=question["question"],
                                student_ans=" ".join(student_answers),
                                expected_ans=" ".join(question["explanation"]),
                                total_score= question.get("marks", 10),
                                guidelines = question["guidelines"]
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
            with open('data/json/quiz_responses_evaluated_LA.json', 'w') as f:
                json.dump(subset_quiz_responses, f, indent=4)

if __name__ == "__main__":
    # results = get_quiz_responses(database_url, quiz_id)
    # with open('quiz_responses.json', 'w') as f:
    #     json.dump(results, f, indent=4)
    # from datetime import datetime
    # class DateTimeEncoder(json.JSONEncoder):
    #     def default(self, obj):
    #         if isinstance(obj, (datetime)):
    #             return obj.isoformat()  # Convert to ISO format
    #         return super().default(obj)
    # questions = get_all_questions("cm5q8fgip0004ga7azlbs71qs")
    # with open('data/json/la_desc_questions.json', 'w') as f:
    #     json.dump(questions, f, indent=4, cls=DateTimeEncoder)
    asyncio.run(bulk_evaluate_quiz_responses(database_url = os.getenv('COCKROACH_DB'), quiz_id = "cm5q8fgip0004ga7azlbs71qs"))