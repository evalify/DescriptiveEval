"""
This module contains functions to evaluate quiz responses in bulk using LLMs and cache the results.
"""

import asyncio
import itertools
import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv
from redis import Redis
from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm

# Custom imports
from model import score, LLMProvider, get_llm, generate_guidelines, score_fill_in_blank
from utils.errors import *
from utils.evaluation.code_eval import evaluate_coding_question
from utils.evaluation.static_eval import evaluate_mcq, evaluate_mcq_with_partial_marking, evaluate_true_false, \
    direct_match
from utils.logger import logger, QuizLogger
from utils.misc import DateTimeEncoder, remove_html_tags, save_quiz_data
from utils.quiz.quiz_report import generate_quiz_report, save_quiz_report
from utils.quiz.quiz_schema import QuizResponseSchema
from utils.quiz.evaluation_logger import EvaluationLogger

load_dotenv()
CACHE_EX = int(os.getenv('CACHE_EX', 3600))  # Cache expiry time in seconds
MAX_RETRIES = int(os.getenv('MAX_RETRIES', 10))  # Maximum number of retries for LLM evaluation


async def get_guidelines(redis_client: Redis, llm, question_id: str, question: str, expected_answer: str,
                         total_score: int):
    """Get the guidelines for a question from the cache."""
    # FIXME: Temporary override to use microLLM
    llm = get_llm(provider=LLMProvider.GROQ, model_name='llama-3.3-70b-versatile')
    cached_guidelines = redis_client.get(question_id + '_guidelines_cache')
    if cached_guidelines:
        return json.loads(cached_guidelines)

    guidelines = None
    errors = []

    for attempt in range(MAX_RETRIES):
        try:
            guidelines = await generate_guidelines(llm, question, expected_answer, total_score, errors)
            if guidelines['guidelines'].startswith(("Error:", "Error processing response:")) or guidelines['status']==403:
                error_msg = guidelines['guidelines']
                logger.warning(
                    f"Attempt {attempt + 1}/{MAX_RETRIES}: Failed to generate guidelines for question {question_id}: {error_msg}")
                errors.append(error_msg)
                continue
            break
        except Exception as e:
            error_msg = f"Unexpected error generating guidelines: {str(e)}"
            logger.warning(f"Attempt {attempt + 1}/{MAX_RETRIES}: {error_msg}")
            errors.append(error_msg)

    if guidelines is None or int(guidelines.get("status", 403)) == 403:
        error_details = "\n".join(errors)
        logger.error(f"Failed to generate guidelines for question {question_id} after {MAX_RETRIES} attempts.\n"
                        f"Errors encountered:\n{error_details}\n"
                        f"Guidelines response: {guidelines if guidelines else 'None'}")
        # FIXME: Temporary error override
        # raise LLMEvaluationError(
            # f"Failed to generate guidelines after {MAX_RETRIES} attempts.\nErrors encountered:\n{error_details}")
        logger.warning(f"Failed to generate guidelines for question {question_id} after {MAX_RETRIES} attempts.\n")
    redis_client.set(f'guidelines:{question_id}_guidelines_cache', json.dumps(guidelines), ex=86400)
    logger.info(f"Successfully generated and cached guidelines for question {question_id}")
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

    Where, question_id can be matched with the questions retrieved from mongo

    :param cursor: PostgresSQL cursor for database operations
    :param redis_client: Redis client for caching
    :param quiz_id: The ID of the quiz to retrieve responses for
    :param save_to_file: Save the responses to a file (default: True)
    """
    cached_responses = redis_client.get(quiz_id + '_responses_evalcache')
    if cached_responses:
        print("Responses Cache hit!")
        save_quiz_data(json.loads(cached_responses), quiz_id, 'responses')
        return json.loads(cached_responses)

    query = """
        SELECT * FROM "QuizResult" WHERE "quizId" = %s AND "isSubmitted"=true;
    """
    cursor.execute(query, (quiz_id,))
    quiz_responses = cursor.fetchall()

    for response in quiz_responses:
        response['id'] = str(response['id'])
        response['submittedAt'] = str(response['submittedAt'])

    redis_client.set(f'responses:{quiz_id}_responses_evalcache', json.dumps(quiz_responses, cls=DateTimeEncoder), ex=CACHE_EX)

    if save_to_file:
        save_quiz_data(quiz_responses, quiz_id, 'responses')
    return quiz_responses


async def set_quiz_response(cursor, conn, response: dict):
    """
    Update the database with the evaluated results, using async thread.

    :param cursor: PostgresSQL cursor for database operations
    :param conn: PostgresSQL connection for database operations
    :param response: The evaluated response to update in the database
    """
    retries = 0
    max_retries = int(os.getenv('DB_MAX_RETRIES', 3))
    while retries < max_retries:
        try:
            await asyncio.to_thread(
                cursor.execute,
                """UPDATE "QuizResult" 
                   SET "responses" = %s, "score" = %s, "totalScore" = %s, "isEvaluated" = 'EVALUATED'
                   WHERE "id" = %s""",
                (json.dumps(response["responses"]), response["score"], response["totalScore"], response["id"])
            )
            await asyncio.to_thread(conn.commit)
            break
        except Exception as e:
            retries += 1
            if retries == max_retries:
                logger.error(f"Failed to update quiz response after {max_retries} retries: {str(e)}")
                raise
            wait_time = (2 ** retries)  # Exponential backoff: 2,4,8 seconds
            logger.warning(f"Retrying database update in {wait_time} seconds... (Attempt {retries}/{max_retries})")
            await asyncio.sleep(wait_time)


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
        save_quiz_data(json.loads(cached_questions), quiz_id, 'questions')
        return json.loads(cached_questions)

    collection = mongo_db['NEW_QUESTIONS']
    query = {"quizId": quiz_id}
    questions = list(collection.find(query))

    for question in questions:
        question['_id'] = str(question['_id'])

    if save_to_file:
        save_quiz_data(questions, quiz_id, 'questions')

    redis_client.set(f'questions:{quiz_id}_questions_evalcache', json.dumps(questions, cls=DateTimeEncoder), ex=CACHE_EX)

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


async def validate_quiz_setup(quiz_id: str, questions: List[dict], responses: List[dict]) -> None:
    """Validate quiz setup before starting evaluation."""
    if not questions:
        raise NoQuestionsError(f"Quiz {quiz_id} has no questions configured")

    if not responses:
        raise NoResponsesError(f"Quiz {quiz_id} has no submitted responses")

    # Validate question completeness
    invalid_questions = []
    for q in questions:
        issues = []
        if 'type' not in q:
            issues.append('missing type')
        if not q.get('mark') and not q.get('marks'):
            issues.append('missing marks')
        if q.get('type', '').upper() in ['MCQ', 'TRUE_FALSE'] and not 'answer' in q:
            issues.append('missing answer')
        if q.get('type', '').upper() == 'CODING' and not 'driverCode' in q:
            issues.append('missing driver code')
        if q.get('type', '').upper() in ['FILL_IN_BLANK', 'DESCRIPTIVE'] and not 'expectedAnswer' in q:
            issues.append('missing expected answer')
        if issues:
            invalid_questions.append(f"Question {q.get('_id')}: {', '.join(issues)}")

    if invalid_questions:
        raise InvalidQuestionError(
            f"Quiz {quiz_id} has invalid questions:\n" +
            "\n".join(invalid_questions)
        )


async def bulk_evaluate_quiz_responses(quiz_id: str, pg_cursor, pg_conn, mongo_db,
                                       redis_client: Redis, save_to_file: bool = True, llm=None,
                                       override_evaluated: bool = False, types_to_evaluate: Optional[Dict[str, bool]] = None):
    """
    Evaluate all responses for a quiz with rubric caching and parallel processing.
    
    Args:
        quiz_id (str): The ID of the quiz to evaluate
        pg_cursor: PostgresSQL cursor for database operations
        pg_conn: PostgresSQL connection for database operations
        mongo_db: MongoDB database instance
        redis_client (Redis): Redis client for caching
        save_to_file (bool): Whether to save results to files
        llm: Optional LLM instance to use for evaluation
        override_evaluated (bool): Whether to re-evaluate already evaluated responses (isEvaluated='EVALUATED')
        types_to_evaluate (dict): List of question types to evaluate (MCQ, DESCRIPTIVE, CODING, TRUE_FALSE, FILL_IN_BLANK)
        
    Raises:
        NoQuestionsError: If no questions are found for the quiz
        NoResponsesError: If no responses are found for the quiz
        InvalidQuestionError: If a question is missing required attributes
        LLMEvaluationError: If LLM evaluation fails after retries
        TotalScoreError: If there are inconsistencies in total scores
        DatabaseConnectionError: If database operations fail
        EvaluationError: For other evaluation-related errors
        ResponseQuestionMismatchError: If response question IDs is not a subset of quiz questions
    """
    # Initialize quiz-specific logger
    qlogger = QuizLogger(quiz_id)
    eval_logger = EvaluationLogger(quiz_id)
    qlogger.info(f"Starting evaluation for quiz {quiz_id}")
    qlogger.info(f"Evaluation parameters: override_evaluated={override_evaluated}, types_to_evaluate={types_to_evaluate}")

    if not types_to_evaluate:
        types_to_evaluate = {
            'MCQ': True,
            'DESCRIPTIVE': True,
            'CODING': True,
            'TRUE_FALSE': True,
            'FILL_IN_BLANK': True
        }

    if override_evaluated:
        qlogger.info("Resetting evaluation status for all responses")
        pg_cursor.execute(
            """UPDATE "QuizResult" SET "isEvaluated" = 'UNEVALUATED' WHERE "quizId" = %s""",
            (quiz_id,)
        )
    try:
        # Get quiz data with better error handling
        try:
            quiz_responses = get_quiz_responses(cursor=pg_cursor, redis_client=redis_client, quiz_id=quiz_id,
                                                save_to_file=save_to_file)
            questions = get_all_questions(mongo_db=mongo_db, redis_client=redis_client, quiz_id=quiz_id,
                                          save_to_file=save_to_file)
            qlogger.info(f"Retrieved {len(quiz_responses)} responses and {len(questions)} questions")
        except Exception as e:
            qlogger.error(f"Failed to fetch quiz data: {str(e)}")
            raise DatabaseConnectionError(f"Failed to fetch quiz data: {str(e)}")

        # Validate quiz setup
        await validate_quiz_setup(quiz_id, questions, quiz_responses)

        # Get evaluation settings with defaults
        evaluation_settings = get_evaluation_settings(pg_cursor, quiz_id) or {}
        if not evaluation_settings:
            qlogger.warning(
                f"No evaluation settings found for quiz {quiz_id}. Using defaults:\n"
                "- Negative marking: False\n"
                "- MCQ partial marking: False"
            )

        negative_marking = evaluation_settings.get("negativeMark", False)
        mcq_partial_marking = evaluation_settings.get("mcqPartialMark", True)

        qlogger.info(f"Evaluation Settings for quiz {quiz_id}:\n")
        qlogger.info(f"Negative Marking: {negative_marking}")
        qlogger.info(f"MCQ Partial Marking: {mcq_partial_marking}")

        # Initialize LLM with API key rotation
        if llm is None:
            qlogger.info("No LLM instance provided. Using default Groq API key rotation")
            keys = [os.getenv(f"GROQ_API_KEY{i if i > 1 else ''}", None) for i in range(1, 6)]
            valid_keys = [key for key in keys if key]
            if not valid_keys:
                raise EvaluationError(
                    "No valid API keys found for evaluation.\n"
                    "Please ensure at least one GROQ_API_KEY is set in environment variables."
                )
            groq_api_keys = itertools.cycle(valid_keys)
            qlogger.info(f"Using {len(valid_keys)} API keys in rotation for evaluation")

        # Count questions by type
        question_count_by_type = {}
        for question in questions:
            q_type = question.get('type', 'UNKNOWN').upper()
            question_count_by_type[q_type] = question_count_by_type.get(q_type, 0) + 1
        time_taken = None
        with logging_redirect_tqdm(loggers=[logger]):
            progress_bar = tqdm(quiz_responses, desc=f"Evaluating {quiz_id}", unit="response", dynamic_ncols=True)
            qlogger.info(f"Starting evaluation for quiz {quiz_id}")
            qlogger.info(f"Questions count by type: {question_count_by_type}")
            qlogger.info(f"Selective evaluation: {types_to_evaluate}")

            save_quiz_data(
                {
                    'status': 'EVALUATING',
                    'error': None,
                    'time_taken': None,
                    'timestamp': str(datetime.now().isoformat()),
                    'questions_count_by_type': question_count_by_type,
                    'selective evaluation': types_to_evaluate
                },
                quiz_id, 'metadata')

            for quiz_result in progress_bar:
                time_taken = progress_bar.format_dict['elapsed']
                qlogger.debug(f"Processing response {quiz_result['id']} for student {quiz_result['studentId']}")
                if quiz_result.get("isEvaluated") == 'EVALUATED':
                    if not override_evaluated:
                        qlogger.info(f"Skipping evaluation for already evaluated quiz response {quiz_result['id']}")
                        continue
                    qlogger.info(f"Re-evaluating quiz response {quiz_result['id']}")
                quiz_result["totalScore"] = 0

                response_question_ids = set(quiz_result["responses"])
                valid_question_ids = {str(q["_id"]) for q in questions}
                invalid_questions = response_question_ids - valid_question_ids
                if invalid_questions:
                    raise ResponseQuestionMismatchError(quiz_id, invalid_questions)

                questions_progress = tqdm(questions, desc=f"ResponseId:{quiz_result['id']}", unit="question",
                                          leave=False, dynamic_ncols=True)
                for question in questions_progress:
                    qid = str(question["_id"])
                    question_type = question.get("type", "").upper()
                    qlogger.debug(f"Evaluating question {qid} of type {question_type}")

                    # Skip question if its type is not in types_to_evaluate
                    if types_to_evaluate and not types_to_evaluate.get(question_type,
                                                                       types_to_evaluate.get(question_type.lower(),
                                                                                             True)):
                        qlogger.info(
                            f"Skipping evaluation for question {qid} of type {question_type} as per types_to_evaluate")
                        continue

                    if not quiz_result["responses"] or qid not in quiz_result["responses"]:
                        continue

                    # Handle old schema conversion
                    if isinstance(quiz_result["responses"].get(qid), list):
                        quiz_result["responses"][qid] = {
                            "student_answer": quiz_result["responses"][qid],
                        }
                        if "questionMarks" in quiz_result:
                            del quiz_result["questionMarks"]

                    # Validate question marks
                    try:
                        if question.get("marks") is not None:
                            question["mark"] = question["marks"]
                        question_total_score = question["mark"]
                        quiz_result["totalScore"] += question_total_score
                    except KeyError as e:
                        raise InvalidQuestionError(
                            f"Question {qid} is missing required 'mark'/'marks' attribute.\n"
                            f"Question data: {json.dumps(question, indent=2)}"
                        )

                    # Question type specific evaluation
                    try:
                        # Track evaluation metadata
                        evaluation_metadata = {
                            "evaluatedAt": datetime.now().isoformat(),
                            "questionType": question_type,
                            "evaluationAttempts": 0  # Will be updated for LLM evaluations
                        }

                        match question.get("type", "").upper():
                            case "MCQ":
                                qlogger.debug(f"Evaluating MCQ question {qid}")
                                student_answers = QuizResponseSchema.get_attribute(quiz_result, qid, 'student_answer')
                                if not student_answers:
                                    qlogger.warning(f"Empty response for MCQ question {qid}")
                                    QuizResponseSchema.set_attribute(quiz_result, qid, 'score', 0)
                                    QuizResponseSchema.set_attribute(quiz_result, qid, 'remarks', 'No answer provided')
                                    continue

                                correct_answers = question.get("answer")
                                if not correct_answers:
                                    raise InvalidQuestionError(
                                        f"Question {qid} is missing correct answer.\n"
                                        f"Question data: {json.dumps(question, indent=2)}"
                                    )

                                try:
                                    if mcq_partial_marking:
                                        mcq_score = await evaluate_mcq_with_partial_marking(
                                            student_answers, correct_answers, question_total_score
                                        )
                                    else:
                                        mcq_score = await evaluate_mcq(
                                            student_answers, correct_answers, question_total_score
                                        )

                                    QuizResponseSchema.set_attribute(quiz_result, qid, 'score', mcq_score)
                                    if negative_marking and mcq_score <= 0:
                                        neg_score = question.get("negativeMark", -question_total_score / 2)
                                        QuizResponseSchema.set_attribute(quiz_result, qid, 'negative_score', neg_score)
                                        # logger.info(f"Applied negative marking ({neg_score}) for incorrect MCQ answer in {qid}")
                                    else:
                                        QuizResponseSchema.set_attribute(quiz_result, qid, 'negative_score', 0)

                                    eval_logger.log_question_evaluation(
                                        qid, question, quiz_result["studentId"], 
                                        quiz_result["responses"][qid],
                                        {
                                            "score": mcq_score,
                                            "negative_score": quiz_result["responses"][qid].get("negative_score", 0)
                                        },
                                        evaluation_metadata
                                    )

                                except Exception as e:
                                    qlogger.error(f"MCQ evaluation failed for question {qid}", exc_info=True)
                                    raise MCQEvaluationError(qid, student_answers, correct_answers)

                            case "DESCRIPTIVE":
                                qlogger.debug(f"Evaluating descriptive question {qid}")
                                clean_question = remove_html_tags(question['question']).strip()
                                student_answer = QuizResponseSchema.get_attribute(quiz_result, qid, 'student_answer')[0]

                                if await direct_match(student_answer, question["expectedAnswer"], strip=True,
                                                      case_sensitive=False):
                                    score_res = {
                                        "score": question_total_score,
                                        "reason": "Exact Match",
                                        "breakdown": "Exact Match - LLM not used"
                                    }
                                else:
                                    current_llm = llm if llm else get_llm(LLMProvider.GROQ, next(groq_api_keys))
                                    question_guidelines = await get_guidelines(
                                        redis_client=redis_client,
                                        question_id=qid,
                                        llm=current_llm,
                                        question=clean_question,
                                        expected_answer=question["expectedAnswer"],
                                        total_score=question_total_score
                                    )

                                    if question_guidelines.get('status', 403) == 403:
                                        continue

                                    errors = []
                                    for attempt in range(MAX_RETRIES):
                                        try:
                                            score_res = await score(
                                                llm=current_llm,
                                                question=clean_question,
                                                student_ans=student_answer,
                                                expected_ans=" ".join(question["expectedAnswer"]),
                                                total_score=question_total_score,
                                                guidelines=question_guidelines,
                                                errors=errors if attempt < 5 else errors+[f"Warning: Attempt remaining {MAX_RETRIES-attempt-1}"]
                                            )

                                            if any(score_res[key].startswith("Error:") for key in
                                                   # TODO: Use status codes instead
                                                   ["breakdown", "rubric"]):
                                                error_msg = f"LLM returned error response: {score_res}"
                                                qlogger.warning(f"Attempt {attempt + 1}/{MAX_RETRIES}: {error_msg}")
                                                qlogger.warning(f"Studentid {quiz_result['studentId']}")
                                                qlogger.warning(f"Quizid {quiz_result['quizId']}")
                                                qlogger.warning(f"Questionid {qid}")
                                                qlogger.warning(f"Student Answer: {student_answer}")
                                                errors.append(error_msg)

                                                if not llm:
                                                    current_llm = get_llm(
                                                        LLMProvider.GROQ,
                                                        next(groq_api_keys),
                                                        'llama-3.3-70b-versatile' if attempt > 5 else None
                                                    )
                                                continue

                                            break
                                        except Exception as e:
                                            error_msg = f"Unexpected error during scoring: {str(e)}"
                                            qlogger.warning(f"Attempt {attempt + 1}/{MAX_RETRIES}: {error_msg}")
                                            errors.append(error_msg)

                                            if not llm:
                                                current_llm = get_llm(
                                                    LLMProvider.GROQ,
                                                    next(groq_api_keys),
                                                    'llama-3.3-70b-versatile' if attempt > 5 else None
                                                )
                                    else:
                                        error_details = "\n".join(errors)
                                        raise LLMEvaluationError(
                                            f"Failed to evaluate response after {MAX_RETRIES} attempts.\n"
                                            f"Quiz ID: {quiz_id}\n"
                                            f"Question ID: {qid}\n"
                                            f"Student Answer: {student_answer[:100]}...\n"
                                            f"Errors encountered:\n{error_details}"
                                        )

                                QuizResponseSchema.set_attribute(quiz_result, qid, 'score', score_res["score"])
                                QuizResponseSchema.set_attribute(quiz_result, qid, 'remarks', score_res['reason'])
                                QuizResponseSchema.set_attribute(quiz_result, qid, 'breakdown', score_res["breakdown"])

                                # Update metadata with LLM attempts
                                evaluation_metadata["evaluationAttempts"] = attempt + 1
                                evaluation_metadata["llmProvider"] = current_llm.__class__.__name__
                                
                                eval_logger.log_question_evaluation(
                                    qid, question, quiz_result["studentId"],
                                    quiz_result["responses"][qid],
                                    score_res,
                                    evaluation_metadata
                                )

                            case "CODING":
                                qlogger.debug(f"Evaluating coding question {qid}")
                                response = QuizResponseSchema.get_attribute(quiz_result, qid, 'student_answer')
                                if not response:
                                    qlogger.warning(f"Empty response for coding question {qid}")
                                    QuizResponseSchema.set_attribute(quiz_result, qid, 'score', 0)
                                    QuizResponseSchema.set_attribute(quiz_result, qid, 'remarks', 'No code submitted')
                                    continue

                                driver_code = question.get("driverCode")
                                test_cases = question.get("testcases", [])
                                if not driver_code or not test_cases:
                                    raise InvalidQuestionError(
                                        f"Question {qid} is missing driver code or test cases.\n"
                                        f"Question data: {json.dumps(question, indent=2)}"
                                    )

                                try:
                                    coding_score, eval_result = await evaluate_coding_question(
                                        student_response=response[0],
                                        driver_code=driver_code,
                                        test_cases_count=len(test_cases)
                                    )
                                    QuizResponseSchema.set_attribute(quiz_result, qid, 'score', coding_score)
                                    if eval_result:  # Add execution result as remarks if available
                                        QuizResponseSchema.set_attribute(quiz_result, qid, 'remarks', eval_result)

                                    eval_logger.log_question_evaluation(
                                        qid, question, quiz_result["studentId"],
                                        quiz_result["responses"][qid],
                                        {
                                            "score": coding_score,
                                            "remarks": eval_result
                                        },
                                        evaluation_metadata
                                    )

                                except Exception as e:
                                    qlogger.error(f"Coding evaluation failed for question {qid}", exc_info=True)
                                    raise CodingEvaluationError(qid, str(e), len(test_cases))

                            case "TRUE_FALSE":
                                qlogger.debug(f"Evaluating True/False question {qid}")
                                response = QuizResponseSchema.get_attribute(quiz_result, qid, 'student_answer')
                                if not response:
                                    qlogger.warning(f"Empty response for True/False question {qid}")
                                    QuizResponseSchema.set_attribute(quiz_result, qid, 'score', 0)
                                    QuizResponseSchema.set_attribute(quiz_result, qid, 'remarks', 'No answer provided')
                                    continue

                                correct_answer = question.get("answer")
                                if correct_answer is None:
                                    raise InvalidQuestionError(
                                        f"Question {qid} is missing correct answer.\n"
                                        f"Question data: {json.dumps(question, indent=2)}"
                                    )

                                try:
                                    tf_score = await evaluate_true_false(response[0], correct_answer,
                                                                         question_total_score)
                                    QuizResponseSchema.set_attribute(quiz_result, qid, 'score', tf_score)
                                    if negative_marking and tf_score <= 0:
                                        neg_score = question.get("negativeMark", -question_total_score / 2)
                                        QuizResponseSchema.set_attribute(quiz_result, qid, 'negative_score', neg_score)
                                        # logger.info(f"Applied negative marking ({neg_score}) for incorrect True/False answer in {qid}")
                                    else:
                                        QuizResponseSchema.set_attribute(quiz_result, qid, 'negative_score', 0)

                                    eval_logger.log_question_evaluation(
                                        qid, question, quiz_result["studentId"],
                                        quiz_result["responses"][qid],
                                        {
                                            "score": tf_score,
                                            "negative_score": quiz_result["responses"][qid].get("negative_score", 0)
                                        },
                                        evaluation_metadata
                                    )

                                except Exception as e:
                                    qlogger.error(f"True/False evaluation failed for question {qid}", exc_info=True)
                                    raise TrueFalseEvaluationError(qid, response[0], correct_answer)

                            case "FILL_IN_BLANK":
                                qlogger.debug(f"Evaluating fill in blank question {qid}")
                                response = QuizResponseSchema.get_attribute(quiz_result, qid, 'student_answer')[0]
                                if not response:
                                    qlogger.warning(f"Empty response for fill in blank question {qid}")
                                    QuizResponseSchema.set_attribute(quiz_result, qid, 'score', 0)
                                    QuizResponseSchema.set_attribute(quiz_result, qid, 'remarks', 'No answer provided')
                                    continue

                                correct_answer = question.get("expectedAnswer")
                                if not correct_answer:
                                    raise InvalidQuestionError(
                                        f"Question {qid} is missing expected answer.\n"
                                        f"Question data: {json.dumps(question, indent=2)}"
                                    )

                                if await direct_match(response, correct_answer, strip=True, case_sensitive=False):
                                    fitb_score = {
                                        'score': question_total_score,
                                        'reason': 'Exact Match'
                                    }
                                else:
                                    current_llm = llm if llm else get_llm(LLMProvider.GROQ, next(groq_api_keys))
                                    clean_question = remove_html_tags(question['question']).strip()

                                    evaluation_attempts = []
                                    for attempt in range(MAX_RETRIES):
                                        try:
                                            fitb_score = await score_fill_in_blank(
                                                llm=current_llm,
                                                question=clean_question,
                                                student_ans=response,
                                                expected_ans=correct_answer,
                                                total_score=question_total_score,
                                            )

                                            if fitb_score is None or fitb_score.get('reason', '').startswith("Error:"):
                                                error_msg = fitb_score.get(
                                                    'reason') if fitb_score else "No response from LLM"
                                                qlogger.warning(
                                                    f"Attempt {attempt + 1}/{MAX_RETRIES} failed for question {qid}. "
                                                    f"Error: {error_msg}"
                                                )
                                                evaluation_attempts.append({
                                                    'error': error_msg,
                                                    'model': current_llm.__class__.__name__
                                                })

                                                if not llm:
                                                    current_llm = get_llm(
                                                        LLMProvider.GROQ,
                                                        next(groq_api_keys),
                                                        'llama-3.3-70b-versatile' if attempt > 5 else None
                                                    )
                                                continue
                                            break

                                        except Exception as e:
                                            error_msg = f"Unexpected error: {str(e)}"
                                            qlogger.warning(
                                                f"Attempt {attempt + 1}/{MAX_RETRIES} failed for question {qid}. "
                                                f"Error: {error_msg}"
                                            )
                                            evaluation_attempts.append({
                                                'error': error_msg,
                                                'model': current_llm.__class__.__name__
                                            })

                                            if not llm:
                                                current_llm = get_llm(
                                                    LLMProvider.GROQ,
                                                    next(groq_api_keys),
                                                    'llama-3.3-70b-versatile' if attempt > 5 else None
                                                )
                                    else:
                                        raise FillInBlankEvaluationError(qid, evaluation_attempts, MAX_RETRIES)

                                QuizResponseSchema.set_attribute(quiz_result, qid, 'score', fitb_score["score"])
                                QuizResponseSchema.set_attribute(quiz_result, qid, 'remarks', fitb_score['reason'])

                                # Update metadata with LLM attempts
                                evaluation_metadata["evaluationAttempts"] = attempt + 1
                                evaluation_metadata["llmProvider"] = current_llm.__class__.__name__
                                
                                eval_logger.log_question_evaluation(
                                    qid, question, quiz_result["studentId"],
                                    quiz_result["responses"][qid],
                                    fitb_score,
                                    evaluation_metadata
                                )

                            case _:
                                qlogger.warning(f"Unhandled question type: {question.get('type')!r} for question {qid}")

                    except Exception as e:
                        qlogger.error(
                            f"Error evaluating question {qid} of type {question.get('type')}:\n"
                            f"Error: {str(e)}\n"
                            f"Question data: {json.dumps(question, indent=2)}\n"
                            f"Response data: {json.dumps(quiz_result.get('responses', {}).get(qid), indent=2)}"
                        )
                        # Log failed evaluation
                        eval_logger.log_question_evaluation(
                            qid, question, quiz_result["studentId"],
                            quiz_result["responses"][qid],
                            {"error": str(e)},
                            {"evaluatedAt": datetime.now().isoformat(), "status": "failed"}
                        )
                        raise

                # Calculate total score including negative marking
                quiz_result["score"] = max(sum([
                    QuizResponseSchema.get_attribute(quiz_result, qid, 'score') +
                    (QuizResponseSchema.get_attribute(quiz_result, qid, 'negative_score') or 0)
                    for qid in quiz_result["responses"].keys()
                ]), 0)

                # Save result back to database
                await set_quiz_response(pg_cursor, pg_conn, quiz_result)
                qlogger.info(f"Response {quiz_result['id']} evaluated. Final score: {quiz_result['score']}")

    except Exception as e:
        qlogger.error(f"Evaluation failed: {str(e)}", exc_info=True)
        if isinstance(e, (NoQuestionsError, NoResponsesError, InvalidQuestionError,
                          LLMEvaluationError, TotalScoreError, DatabaseConnectionError)):
            # These are already formatted nicely, just log them
            qlogger.error(str(e))
        else:
            # Unexpected errors need more context
            qlogger.error(
                f"Unexpected error during evaluation of quiz {quiz_id}:\n"
                f"Error Type: {type(e).__name__}\n"
                f"Error Details: {str(e)}\n"
                "Stack trace:", exc_info=True
            )

        save_quiz_data(
            {
                'status': 'FAILED',
                'error': str(e),
                'time_taken': time_taken,
                'timestamp': str(datetime.now().isoformat()),
                'questions_count_by_type': question_count_by_type,
                'selective evaluation': types_to_evaluate
            },
            quiz_id, 'metadata')

        # raise

    else:
        try:
            # Generate and save quiz report
            qlogger.info("Generating quiz report")
            quiz_report = await generate_quiz_report(quiz_id, quiz_responses, questions)
            await save_quiz_report(quiz_id, quiz_report, pg_cursor, pg_conn, save_to_file)
            qlogger.info("Quiz report generated and saved successfully")

            # Update evaluation status
            qlogger.info("Updating quiz evaluation status")
            pg_cursor.execute(
                """UPDATE "Quiz" SET "isEvaluated" = 'EVALUATED' WHERE "id" = %s""",
                (quiz_id,)
            )
            pg_conn.commit()

            save_quiz_data(
                {
                    'status': 'EVALUATED',
                    'error': None,
                    'time_taken': time_taken,
                    'timestamp': str(datetime.now().isoformat()),
                    'questions_count_by_type': question_count_by_type,
                    'selective evaluation': types_to_evaluate
                },
                quiz_id, 'metadata')

        except Exception as e:
            qlogger.error(f"Error in evaluation cleanup for quiz {quiz_id}: {str(e)}", exc_info=True)
            raise EvaluationError(f"Evaluation completed but failed during cleanup: {str(e)}")

    finally:
        if save_to_file:
            qlogger.info("Saving final evaluation results")
            save_quiz_data(quiz_responses, quiz_id, 'responses_evaluated')
        qlogger.info("Evaluation complete")

    return quiz_responses


if __name__ == "__main__":
    from utils.database import get_postgres_cursor, get_mongo_client, get_redis_client

    my_pg_cursor, my_pg_conn = get_postgres_cursor()
    my_mongo_db = get_mongo_client()
    my_redis_client = get_redis_client()

    my_quiz_id = "cm6fzxb3h01bbxy8pp7330wz9"
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
