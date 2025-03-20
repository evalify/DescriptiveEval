"""
This module contains functions to evaluate quiz responses in bulk using LLMs and cache the results.
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dotenv import load_dotenv
from redis import Redis
from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm
import threading
from app.database.postgres import get_db_cursor
from contextlib import asynccontextmanager

# Custom imports
from .utils.db_api import (
    get_quiz_responses,
    get_evaluation_settings,
    get_all_questions,
    set_quiz_response,
    get_guidelines,
)
from app.core.exceptions import (
    NoQuestionsError,
    NoResponsesError,
    InvalidQuestionError,
    DatabaseConnectionError,
    EvaluationError,
    ResponseQuestionMismatchError,
)
from app.core.logger import logger, QuizLogger
from app.config.constants import (
    CACHE_EX,
    DESC_EVAL_TIME,
    FITB_EVAL_TIME,
    EVAL_BATCH_SIZE,
    BATCH_TIMEOUT,
    EVAL_MAX_RETRIES,
)
from app.utils.misc import save_quiz_data, remove_html_tags
from .utils.quiz.quiz_report import generate_quiz_report, save_quiz_report
from .utils.evaltools.evaluator import ResponseEvaluator

load_dotenv()


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
    override_cache: bool = False,
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
        override_cache (bool): Override the cache and fetch fresh data

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
        descriptive_tasks = []
        descriptive_questions = []
        for question in questions:
            q_type = question.get("type", "UNKNOWN").upper()
            question_count_by_type[q_type] = question_count_by_type.get(q_type, 0) + 1
            # If question is Descriptive, check if it has guidelines
            if q_type == "DESCRIPTIVE" and not question.get("guidelines"):
                qlogger.warning(
                    f"Descriptive question {question['_id']} has no evaluation guidelines. Generating..."
                )
                descriptive_questions.append(question)
                descriptive_tasks.append(
                    get_guidelines(
                        redis_client=redis_client,
                        question_id=question["_id"],
                        llm=llm,
                        question=remove_html_tags(question["question"]).strip(),
                        expected_answer=question["expectedAnswer"],
                        total_score=question.get("marks", question.get("mark", 0)),
                    )
                )
        if descriptive_tasks:
            guidelines_results = await asyncio.gather(*descriptive_tasks)
            for question, guidelines in zip(descriptive_questions, guidelines_results):
                question["guidelines"] = guidelines

        # Initialize response evaluator
        evaluator = ResponseEvaluator(quiz_id, questions, evaluation_settings, llm)

        # Create a thread pool for database operations
        # thread_pool = ThreadPoolExecutor(max_workers=10)

        @asynccontextmanager
        async def get_db_connection():
            """Async context manager for database connections"""
            with get_db_cursor() as (cursor, conn):
                yield cursor, conn

        async def save_response(evaluated_result):
            """Save a single response with its own database connection"""
            async with get_db_connection() as (
                cursor,
                conn,
            ):  # FIXME: Use me or Remove me
                await set_quiz_response(cursor, conn, evaluated_result)

        async def process_response(
            quiz_result, index, questions, types_to_evaluate, evaluator, progress_bar
        ):
            """Process a single response with proper error handling, connection management, and monitoring"""
            # start_time = time.monotonic()
            # phase_times = {}

            try:
                qlogger.debug(f"Started processing response {index}")

                # Validation phase
                # validation_start = time.monotonic()
                response_question_ids = set(quiz_result["responses"])
                valid_question_ids = {str(q["_id"]) for q in questions}
                invalid_questions = response_question_ids - valid_question_ids
                if invalid_questions:
                    raise ResponseQuestionMismatchError(quiz_id, invalid_questions)
                # phase_times["validation"] = time.monotonic() - validation_start
                update_progress(
                    redis_client, quiz_id, progress_bar, qlogger, "validation"
                )

                # Evaluation phase
                # eval_start = time.monotonic()
                qlogger.info(f"[Response {index}] Starting evaluation...")
                update_progress(
                    redis_client, quiz_id, progress_bar, qlogger, "evaluation_start"
                )
                num_desc = question_count_by_type.get("DESCRIPTIVE", 0)
                num_fitb = question_count_by_type.get("FILL_IN_BLANK", 0)
                computed_timeout = max(
                    (num_desc * DESC_EVAL_TIME) + (num_fitb * FITB_EVAL_TIME), 90
                )
                attempt = 0
                for attempt in range(EVAL_MAX_RETRIES):
                    try:

                        async def eval_with_heartbeat():
                            task = asyncio.create_task(
                                evaluator.evaluate_response(
                                    quiz_result, types_to_evaluate
                                )
                            )
                            update_progress(
                                redis_client,
                                quiz_id,
                                progress_bar,
                                qlogger,
                                "evaluation_in_progress",
                            )
                            heartbeat_interval = 10  # seconds between heartbeat logs
                            while not task.done():
                                await asyncio.sleep(heartbeat_interval)
                                qlogger.debug(
                                    f"[Response {index}] Heartbeat: Evaluation still running"
                                )
                            return await task

                        evaluated_result = await asyncio.wait_for(
                            asyncio.shield(eval_with_heartbeat()),
                            timeout=computed_timeout,
                        )
                        update_progress(
                            redis_client,
                            quiz_id,
                            progress_bar,
                            qlogger,
                            "evaluation_in_progress",
                        )
                    except asyncio.TimeoutError:
                        qlogger.error(
                            f"[Response {index}] Evaluation timed out (>{computed_timeout}). Retrying {attempt + 1}"
                        )
                        continue
                    else:
                        break
                else:
                    raise TimeoutError(
                        f"Failed to evaluate response {index} after {attempt + 1} attempts"
                    )
                qlogger.info(f"[Response {index}] Evaluation completed")
                # phase_times["evaluation"] = time.monotonic() - eval_start

                # Save phase
                # save_start = time.monotonic()
                qlogger.debug(f"[Response {index}] Starting database save...")
                # with get_db_cursor() as (cursor, conn):
                await set_quiz_response(pg_cursor, pg_conn, evaluated_result)
                qlogger.debug(f"[Response {index}] Database save completed")
                # phase_times["save"] = time.monotonic() - save_start

                # total_time = time.monotonic() - start_time    # FIXME: This blocks execution!!!
                # qlogger.info(
                #     f"Response {index} completed in {timedelta(seconds=total_time):.2f}. "
                #     f"Phases: validation={timedelta(seconds=phase_times['validation']):.2f}, "
                #     f"evaluation={timedelta(seconds=phase_times['evaluation']):.2f}, "
                #     f"save={timedelta(seconds=phase_times['save']):.2f}"
                # )

                # Update progress atomically
                with threading.Lock():
                    progress_bar.update(1)
                    update_progress(
                        redis_client,
                        quiz_id,
                        progress_bar,
                        qlogger,
                        "evaluation_in_progress",
                    )

                return {
                    "result": evaluated_result,
                    "processing_time": 0,  # total_time, #FIXME:DO something!
                    "phase_times": 0,  # phase_times,
                }

            except Exception as e:
                logger.error(
                    f"Error processing response {index}: {str(e)}", exc_info=True
                )
                raise Exception(
                    f"Error processing response (unable to evaluate/save) {index}: {str(e)}"
                )
                # total_time = time.monotonic() - start_time
                # qlogger.error(
                #     f"Error processing response {index} after {timedelta(seconds=total_time):.2f}. "
                #     f"Phase times: {phase_times}. Error: {str(e)}",
                #     exc_info=True,
                # )
                return None

        with logging_redirect_tqdm(loggers=[logger]):
            unevaluated_quiz_responses = []  # Filter Evaluated Responses
            evaluated_quiz_responses = []  # Store Evaluated Responses
            for quiz_result in quiz_responses:
                if quiz_result.get("isEvaluated") == "EVALUATED":
                    if not override_evaluated:
                        qlogger.info(
                            f"Skipping evaluation for already evaluated quiz response {quiz_result['id']}"
                        )
                        evaluated_quiz_responses.append(quiz_result)
                        continue
                    else:
                        qlogger.info(
                            f"Re-evaluating quiz response {quiz_result['id']} due to override flag"
                        )
                        quiz_result["isEvaluated"] = "UNEVALUATED"

                unevaluated_quiz_responses.append(quiz_result)

            progress_bar = tqdm(
                quiz_responses,
                desc=f"Evaluating {quiz_id}",
                unit="response",
                dynamic_ncols=True,
            )
            # Update progress bar to initialize with the  0 + number of evaluated responses
            progress_bar.n = len(evaluated_quiz_responses)

            update_progress(
                redis_client, quiz_id, progress_bar, qlogger, "initializing"
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

            total_responses = len(unevaluated_quiz_responses)
            # processed_results = []
            batch_times = []

            # Process responses in batches
            for i in range(0, total_responses, EVAL_BATCH_SIZE):
                # batch_start = time.monotonic()
                batch = unevaluated_quiz_responses[i : i + EVAL_BATCH_SIZE]
                batch_number = i // EVAL_BATCH_SIZE + 1
                qlogger.info(f"Starting batch {batch_number} ({len(batch)} responses)")

                tasks = [
                    process_response(
                        quiz_result,
                        index,
                        questions,
                        types_to_evaluate,
                        evaluator,
                        progress_bar,
                    )
                    for index, quiz_result in enumerate(batch, start=i + 1)
                ]

                # Process batch with timeout
                try:
                    await asyncio.gather(*tasks, return_exceptions=True)
                    progress_bar.refresh()
                    # processed_results.extend(batch_results)
                    # batch_results = await asyncio.wait_for(
                    #     asyncio.gather(*tasks, return_exceptions=True),
                    #     timeout=BATCH_TIMEOUT,
                    # )

                    # # Process results and collect statistics
                    # valid_results = []
                    # batch_stats = {
                    #     "total": len(batch_results),
                    #     "successful": 0,
                    #     "failed": 0,
                    #     "avg_time": 0,
                    #     "max_time": 0,
                    # }

                    # for result in batch_results:
                    #     if result and not isinstance(result, Exception):
                    #         valid_results.append(result["result"])
                    #         batch_stats["successful"] += 1
                    #         batch_stats["avg_time"] += result["processing_time"]
                    #         batch_stats["max_time"] = max(
                    #             batch_stats["max_time"], result["processing_time"]
                    #         )
                    #     else:
                    #         batch_stats["failed"] += 1

                    # if batch_stats["successful"] > 0:
                    #     batch_stats["avg_time"] /= batch_stats["successful"]

                    # batch_time = time.monotonic() - batch_start
                    # batch_times.append(batch_time)

                    # qlogger.info(
                    #     f"Batch {batch_number} completed in {timedelta(seconds=batch_time):.2f}. "
                    #     f"Success: {batch_stats['successful']}/{batch_stats['total']}, "
                    #     f"Avg time: {timedelta(seconds=batch_stats['avg_time']):.2f}, "
                    #     f"Max time: {timedelta(seconds=batch_stats['max_time']):.2f}"
                    # )

                    #

                except asyncio.TimeoutError:
                    qlogger.error(
                        f"FAILED: Batch {batch_number} timed out after {BATCH_TIMEOUT} seconds"
                    )
                    # Don't raise here, continue with next batch
                except Exception as e:
                    qlogger.error(
                        f"Batch {batch_number} failed: {str(e)}", exc_info=True
                    )
                    continue

                time_taken = progress_bar.format_dict.get("elapsed", 0)

        # Log overall statistics
        if batch_times:
            avg_batch_time = sum(batch_times) / len(batch_times)
            max_batch_time = max(batch_times)
            qlogger.info(
                f"Evaluation completed. "
                f"Total batches: {len(batch_times)}, "
                f"Avg batch time: {timedelta(seconds=avg_batch_time):.2f}, "
                f"Max batch time: {timedelta(seconds=max_batch_time):.2f}"
            )

        # Add the evaluated responses to the main list, for the sake of saving to file and generating report
        quiz_responses = evaluated_quiz_responses + unevaluated_quiz_responses

        # Mark progress as complete
        update_progress(
            redis_client, quiz_id, progress_bar, qlogger, "evaluation_complete"
        )

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
                f"Error in evaluation creating quizreport/setting quiz as evaluated for quiz {quiz_id}: {str(e)}",
                exc_info=True,
            )
            raise EvaluationError(
                f"Evaluation completed but failed during quizreport/setting quiz as evaluated: {str(e)}"
            )

    finally:
        # thread_pool.shutdown()
        if save_to_file:
            qlogger.info("Saving final evaluation results")
            save_quiz_data(quiz_responses, quiz_id, "responses_evaluated")
        qlogger.info("Evaluation complete")

    return quiz_responses


def update_progress(
    redis_client: Redis,
    quiz_id: str,
    progress_bar: tqdm,
    logger=None,
    phase: str = None,
) -> None:
    """
    Update progress tracking in Redis for a quiz evaluation.

    Args:
        redis_client: Redis client instance
        quiz_id: The ID of the quiz being evaluated
        progress_bar: tqdm progress bar instance
        logger: Optional logger instance for debug messages
        phase: Optional current evaluation phase being tracked
    """
    try:
        progress = progress_bar.n
        total = progress_bar.total
        progress_percent = (progress / total) * 100 if total > 0 else 0
        current_time = datetime.now()

        elapsed = progress_bar.format_dict.get("elapsed", 0)
        rate = progress_bar.format_dict.get("rate", 0)

        # Get remaining time
        remaining_time = (total - progress) / rate if rate and total else 0

        progress_data = {
            "progress": round(progress_percent, 2),
            "total": total,
            "current": progress,
            "elapsed": elapsed,
            "rate": rate,
            "remaining": remaining_time,
            "last_update": current_time.isoformat(),
            "current_phase": phase,
        }

        # Use a short expiry time to auto-cleanup stale progress
        redis_client.setex(
            f"quiz_progress:{quiz_id}",
            CACHE_EX,  # Use same cache expiry time as other quiz data
            json.dumps(progress_data),
        )

        if logger:
            status = f" [{phase}]" if phase else ""
            logger.debug(
                f"Progress updated{status}: {progress}/{total} ({progress_percent:.1f}%) at {current_time.strftime('%H:%M:%S')}"
            )

    except Exception as e:
        if logger:
            logger.warning(f"Failed to update progress tracking: {str(e)}")


if __name__ == "__main__":
    from app.database.postgres import get_postgres_cursor
    from app.database.mongo import get_mongo_client
    from app.database.redis import get_redis_client

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
