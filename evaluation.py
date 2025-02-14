"""
This module contains functions to evaluate quiz responses in bulk using LLMs and cache the results.
"""

import asyncio
import os
from datetime import datetime
from typing import List, Dict, Optional
import json
from dotenv import load_dotenv
from redis import Redis
from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm
import threading
# Custom imports
from utils.db_api import (
    get_quiz_responses,
    get_evaluation_settings,
    get_all_questions,
    set_quiz_response,
    set_quiz_responses,
)
from utils.errors import (
    NoQuestionsError,
    NoResponsesError,
    InvalidQuestionError,
    TotalScoreError,
    DatabaseConnectionError,
    EvaluationError,
    ResponseQuestionMismatchError,
)
from utils.logger import logger, QuizLogger
from utils.misc import DateTimeEncoder, save_quiz_data
from utils.quiz.quiz_report import generate_quiz_report, save_quiz_report
from utils.quiz.evaluation_logger import EvaluationLogger
from utils.evaluation.evaluator import ResponseEvaluator

load_dotenv()
CACHE_EX = int(os.getenv("CACHE_EX", 3600))  # Cache expiry time in seconds


async def validate_quiz_setup(
    quiz_id: str, questions: List[dict], responses: List[dict]
) -> None:
    """Validate quiz setup before starting evaluation."""
    if not questions:
        raise NoQuestionsError(f"Quiz {quiz_id} has no questions configured")

    if not responses:
        raise NoResponsesError(f"Quiz {quiz_id} has no submitted responses")

    # Validate question completeness
    invalid_questions = []
    for q in questions:
        issues = []
        if "type" not in q:
            issues.append("missing type")
        if not q.get("mark") and not q.get("marks"):
            issues.append("missing marks")
        if q.get("type", "").upper() in ["MCQ", "TRUE_FALSE"] and "answer" not in q:
            issues.append("missing answer")
        if q.get("type", "").upper() == "CODING" and "driverCode" not in q:
            issues.append("missing driver code")
        if (
            q.get("type", "").upper() in ["FILL_IN_BLANK", "DESCRIPTIVE"]
            and "expectedAnswer" not in q
        ):
            issues.append("missing expected answer")
        if issues:
            invalid_questions.append(f"Question {q.get('_id')}: {', '.join(issues)}")

    if invalid_questions:
        raise InvalidQuestionError(
            f"Quiz {quiz_id} has invalid questions:\n" + "\n".join(invalid_questions)
        )


async def bulk_evaluate_quiz_responses(
    quiz_id: str,
    pg_cursor,
    pg_conn,
    mongo_db,
    redis_client: Redis,
    save_to_file: bool = True,
    llm=None,
    override_evaluated: bool = False,
    types_to_evaluate: Optional[Dict[str, bool]] = None,
    override_cache : bool = False,
):
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
        override_evaluated (bool): Whether to re-evaluate already evaluated responses
        types_to_evaluate (dict): List of question types to evaluate

    Returns:
        List of evaluated quiz responses
    """
    # Initialize loggers
    qlogger = QuizLogger(quiz_id)
    qlogger.info(f"Starting evaluation for quiz {quiz_id}")
    qlogger.info(
        f"Evaluation parameters: override_evaluated={override_evaluated}, types_to_evaluate={types_to_evaluate}"
    )

    question_count_by_type = {}
    quiz_responses = None
    time_taken = None

    if not types_to_evaluate:
        types_to_evaluate = {
            "MCQ": True,
            "DESCRIPTIVE": True,
            "CODING": True,
            "TRUE_FALSE": True,
            "FILL_IN_BLANK": True,
        }

    if override_evaluated:
        qlogger.info("Resetting evaluation status for all responses")
        pg_cursor.execute(
            """UPDATE "QuizResult" SET "isEvaluated" = 'UNEVALUATED' WHERE "quizId" = %s""",
            (quiz_id,),
        )

    try:
        # Get quiz data
        try:
            quiz_responses = get_quiz_responses(
                cursor=pg_cursor,
                redis_client=redis_client,
                quiz_id=quiz_id,
                save_to_file=save_to_file,
                override_cache=override_cache,
            )
            questions = get_all_questions(
                mongo_db=mongo_db,
                redis_client=redis_client,
                quiz_id=quiz_id,
                save_to_file=save_to_file,
                override_cache=override_cache,
            )
            qlogger.info(
                f"Retrieved {len(quiz_responses)} responses and {len(questions)} questions"
            )
        except Exception as e:
            qlogger.error(f"Failed to fetch quiz data: {str(e)}")
            raise DatabaseConnectionError(f"Failed to fetch quiz data: {str(e)}")

        # Validate quiz setup
        await validate_quiz_setup(quiz_id, questions, quiz_responses)

        # Get evaluation settings
        evaluation_settings = get_evaluation_settings(pg_cursor, quiz_id)

        # Count questions by type
        for question in questions:
            q_type = question.get("type", "UNKNOWN").upper()
            question_count_by_type[q_type] = question_count_by_type.get(q_type, 0) + 1

        # Initialize response evaluator
        evaluator = ResponseEvaluator(quiz_id, questions, evaluation_settings, llm)

        with logging_redirect_tqdm(loggers=[logger]):
            tmp = []  # Filter Evaluated Responses
            for quiz_result in quiz_responses:
                if quiz_result.get("isEvaluated") == "EVALUATED":
                    if not override_evaluated:
                        qlogger.info(
                            f"Skipping evaluation for already evaluated quiz response {quiz_result['id']}"
                        )
                        continue
                    else:
                        qlogger.info(
                            f"Re-evaluating quiz response {quiz_result['id']} due to override flag"
                        )
                        quiz_result["isEvaluated"] = "UNEVALUATED"

                tmp.append(quiz_result)
            quiz_responses = tmp

            progress_bar = tqdm(
                quiz_responses,
                desc=f"Evaluating {quiz_id}",
                unit="response",
                dynamic_ncols=True,
            )
            qlogger.info(f"Questions count by type: {question_count_by_type}")
            qlogger.info(f"Selective evaluation: {types_to_evaluate}")

            save_quiz_data(
                {
                    "status": "EVALUATING",
                    "error": None,
                    "time_taken": None,
                    "timestamp": str(datetime.now().isoformat()),
                    "questions_count_by_type": question_count_by_type,
                    "selective evaluation": types_to_evaluate,
                },
                quiz_id,
                "metadata",
            )

            EVAL_BATCH_SIZE = int(os.getenv("EVAL_BATCH_SIZE", 5))
            total_responses = len(quiz_responses)
            processed_results = []

            # Process responses in batches
            for i in range(0, total_responses, EVAL_BATCH_SIZE):
                batch = quiz_responses[i : i + EVAL_BATCH_SIZE]
                tasks = []
                for index, quiz_result in enumerate(batch, start=1):
                    async def process_response(qr=quiz_result, index=index):
                        try:
                            print("Processing response ", index)
                            # Validate response question IDs
                            response_question_ids = set(qr["responses"])
                            valid_question_ids = {str(q["_id"]) for q in questions}
                            invalid_questions = response_question_ids - valid_question_ids
                            if invalid_questions:
                                raise ResponseQuestionMismatchError(
                                    quiz_id, invalid_questions
                                )

                            # Evaluate single response
                            evaluated_result = await evaluator.evaluate_response(
                                qr, types_to_evaluate
                            )

                            # Save result back to Redis and database
                            print("Saving response ", index)
                            await set_quiz_response(pg_cursor, pg_conn, evaluated_result)   # pool this!!
                            qlogger.info(
                                f"Response {evaluated_result['id']} evaluated. Final score: {evaluated_result['score']}"
                            )


                            with threading.Lock():
                                progress_bar.update(1)

                            print("Response processed", index)
                        except Exception:
                            print("Error in process_response", index)
                            return None
                        else:
                            return evaluated_result

                    tasks.append(process_response())
                batch_results = await asyncio.gather(*tasks)
                processed_results.extend(batch_results)
                time_taken = progress_bar.format_dict.get("elapsed", 0)

    except Exception as e:
        qlogger.error(f"Evaluation failed: {str(e)}", exc_info=True)

        save_quiz_data(
            {
                "status": "FAILED",
                "error": str(e),
                "time_taken": time_taken,
                "timestamp": str(datetime.now().isoformat()),
                "questions_count_by_type": question_count_by_type,
                "selective evaluation": types_to_evaluate,
            },
            quiz_id,
            "metadata",
        )

        # raise

    else:
        try:
            # Generate and save quiz report
            qlogger.info("Generating quiz report")
            quiz_report = await generate_quiz_report(quiz_id, quiz_responses, questions)
            await save_quiz_report(
                quiz_id, quiz_report, pg_cursor, pg_conn, save_to_file
            )
            qlogger.info("Quiz report generated and saved successfully")

            # Update evaluation status
            qlogger.info("Updating quiz evaluation status")
            pg_cursor.execute(
                """UPDATE "Quiz" SET "isEvaluated" = 'EVALUATED' WHERE "id" = %s""",
                (quiz_id,),
            )
            pg_conn.commit()

            save_quiz_data(
                {
                    "status": "EVALUATED",
                    "error": None,
                    "time_taken": time_taken,
                    "timestamp": str(datetime.now().isoformat()),
                    "questions_count_by_type": question_count_by_type,
                    "selective evaluation": types_to_evaluate,
                },
                quiz_id,
                "metadata",
            )

        except Exception as e:
            qlogger.error(
                f"Error in evaluation cleanup for quiz {quiz_id}: {str(e)}",
                exc_info=True,
            )
            raise EvaluationError(
                f"Evaluation completed but failed during cleanup: {str(e)}"
            )

    finally:
        if save_to_file:
            qlogger.info("Saving final evaluation results")
            save_quiz_data(quiz_responses, quiz_id, "responses_evaluated")
        qlogger.info("Evaluation complete")

    return quiz_responses


if __name__ == "__main__":
    from utils.database import get_postgres_cursor, get_mongo_client, get_redis_client

    my_pg_cursor, my_pg_conn = get_postgres_cursor()
    my_mongo_db = get_mongo_client()
    my_redis_client = get_redis_client()

    my_quiz_id = "cm6fzxb3h01bbxy8pp7330wz9"
    # Evaluate quiz responses
    asyncio.run(
        bulk_evaluate_quiz_responses(
            quiz_id=my_quiz_id,
            pg_cursor=my_pg_cursor,
            pg_conn=my_pg_conn,
            mongo_db=my_mongo_db,
            redis_client=my_redis_client,
            save_to_file=True,
            types_to_evaluate={
                "MCQ": False,
                "DESCRIPTIVE": False,
                "CODING": False,
                "TRUE_FALSE": False,
                "FILL_IN_BLANK": False,
            },
        )
    )

    # Get quiz results
    # my_results = get_quiz_responses(my_pg_cursor, my_redis_client, my_quiz_id)

    # Get all questions
    # my_questions = get_all_questions(my_mongo_db, my_redis_client, my_quiz_id)
