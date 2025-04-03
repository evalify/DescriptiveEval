"""
This module contains functions to generate and save a report for a quiz.

The report includes the following data:
Quiz Report:  {
                quizId,
                avgScore,
                maxScore,
                minScore,
                totalScore,
                totalStudents: scores.length,
                questionStats,
                markDistribution
            }
where,
questionStats:  [{
                questionId,
                questionText: question.question,
                correct,
                incorrect,
                totalAttempts: correct + incorrect,
                avgMarks: totalMarksObtained / quizResults.length,
                maxMarks: question.marks
            }, ...]

markDistribution = {
            excellent, // 80-100%
            good: // 60-79%
            average,  // 40-59%
            poor,      // 0-39%
        }
"""

import asyncio
import json
import uuid
from typing import Any, Dict, List

from app.core.logger import QuizLogger
from app.utils.misc import save_quiz_data
from app.config.constants import DB_MAX_RETRIES
from app.core.exceptions import EvaluationError
import psycopg2
from psycopg2.errors import QueryCanceledError
from app.database.postgres import get_db_connection_no_context


async def generate_quiz_report(
    quiz_id: str, quiz_results: List[Dict[str, Any]], questions: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Generate a report for a quiz
    :param quiz_id: Quiz ID
    :param quiz_results: Results of the quiz
    :param questions: List of questions in the quiz
    :return: Quiz report
    """
    assert len(quiz_results) > 0, "No quiz results found"
    qlogger = QuizLogger(quiz_id)
    qlogger.debug(
        f"Starting report generation with {len(quiz_results)} results and {len(questions)} questions"
    )

    scores = [result["score"] for result in quiz_results]
    total_score = set(result["totalScore"] for result in quiz_results)
    if len(total_score) > 1:
        qlogger.warning(f"Multiple total scores found: {total_score}")
    total_score = max(total_score)
    if total_score <= 0:
        msg = f"Invalid total score: {total_score}"
        qlogger.error(msg)
        raise ValueError(msg)

    avg_score = sum(scores) / len(scores)
    max_score = max(scores)
    min_score = min(scores)
    normalized_scores = [(score / total_score) * 100 for score in scores]

    qlogger.debug(
        f"Score statistics - Avg: {avg_score:.2f}, Max: {max_score}, Min: {min_score}"
    )

    question_stats = []
    for question in questions:
        question_id = question["_id"]
        for result in quiz_results:
            if isinstance(result["responses"].get(question_id), list):
                raise EvaluationError(
                    f"Response is unevaluated for at least one student {result['studentId']}\n"
                    f"Responses are in their original (unevaluated) schema\n"
                    f"This is usually a mild cascade error, check the evaluation for errors"
                )
            if result["responses"].get(question_id, {}).get("score", 0) is None:
                raise EvaluationError(
                    f"Question {question_id} does not have a mark assigned for student {result['studentId']}"
                )
        try:
            correct = sum(
                1
                for result in quiz_results
                if float(result["responses"].get(question_id, {}).get("score", 0))
                >= 0.6 * float(question["mark"])
            )
        except Exception as e:
            raise EvaluationError(f"Error during: {str(e)}")  # TODO: Implement Error
        incorrect = len(quiz_results) - correct
        total_marks_obtained = sum(
            result["responses"].get(question_id, {}).get("score", 0)
            for result in quiz_results
        )

        stats = {
            "questionId": question_id,
            "questionText": question["question"],
            "correct": correct,
            "incorrect": incorrect,
            "totalAttempts": correct + incorrect,
            "avgMarks": total_marks_obtained / len(quiz_results),
            "maxMarks": question["mark"],
        }
        question_stats.append(stats)
        qlogger.debug(
            f"Question {question_id} stats - Correct: {correct}, Incorrect: {incorrect}, Avg marks: {stats['avgMarks']:.2f}"
        )

    mark_distribution = {
        "excellent": sum(1 for score in normalized_scores if 80 <= score <= 100),
        "good": sum(1 for score in normalized_scores if 60 <= score <= 79),
        "average": sum(1 for score in normalized_scores if 40 <= score <= 59),
        "poor": sum(1 for score in normalized_scores if 0 <= score <= 39),
    }

    qlogger.info(
        f"Mark distribution - Excellent: {mark_distribution['excellent']}, Good: {mark_distribution['good']}, Average: {mark_distribution['average']}, Poor: {mark_distribution['poor']}"
    )

    return {
        "quizId": quiz_id,
        "avgScore": avg_score,
        "maxScore": max_score,
        "minScore": min_score,
        "totalScore": total_score,
        "totalStudents": len(quiz_results),
        "questionStats": question_stats,
        "markDistribution": mark_distribution,
    }


async def save_quiz_report(
    quiz_id: str, report: Dict[str, Any], cursor, conn, save_to_file: bool = True
) -> None:
    """
    Save the quiz report to the database and optionally to a file
    :param quiz_id: Quiz ID
    :param report: Quiz report data
    :param cursor: Database cursor
    :param conn: Database connection
    :param save_to_file: Whether to save to a file (default: True)
    """
    qlogger = QuizLogger(quiz_id)
    timeout = 30  # seconds
    retries = 0
    max_retries = DB_MAX_RETRIES

    new_cursor = False
    while retries < max_retries:
        try:
            if retries == max_retries - 1:
                # At last retry, get a new connection
                qlogger.warning(
                    f"Retrying to get a new connection for quiz report {quiz_id} (attempt {retries + 1})"
                )
                cursor, conn = get_db_connection_no_context()
                new_cursor = True

            # Set statement timeout at session level
            cursor.execute("SET LOCAL statement_timeout = %s", (timeout * 1000,))

            # Save to database
            qlogger.debug("Attempting to save report to database")
            async with asyncio.timeout(timeout):
                await asyncio.to_thread(
                    cursor.execute,
                    """INSERT INTO "QuizReport" (
                        "id", "quizId", "maxScore", "avgScore", "minScore", 
                        "totalScore", "totalStudents", "questionStats", "markDistribution", "evaluatedAt"
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT ("quizId") 
                    DO UPDATE SET 
                        "maxScore" = EXCLUDED."maxScore",
                        "avgScore" = EXCLUDED."avgScore",
                        "minScore" = EXCLUDED."minScore",
                        "totalScore" = EXCLUDED."totalScore",
                        "totalStudents" = EXCLUDED."totalStudents",
                        "questionStats" = EXCLUDED."questionStats",
                        "markDistribution" = EXCLUDED."markDistribution",
                        "evaluatedAt" = NOW()
                    """,
                    (
                        uuid.uuid4().hex,
                        quiz_id,
                        report["maxScore"],
                        report["avgScore"],
                        report["minScore"],
                        report["totalScore"],
                        report["totalStudents"],
                        json.dumps(report["questionStats"]),
                        json.dumps(report["markDistribution"]),
                    ),
                )
                await asyncio.to_thread(conn.commit)

            qlogger.info("Quiz report saved to database successfully")

            qlogger.debug("Attempting to update quiz status in database")
            async with asyncio.timeout(timeout):
                await asyncio.to_thread(
                    cursor.execute,
                    """UPDATE "Quiz" SET "isEvaluated" = 'EVALUATED' WHERE "id" = %s""",
                    (quiz_id,),
                )
                await asyncio.to_thread(conn.commit)
            qlogger.info("Quiz status updated to EVALUATED successfully")

            # Save to file if requested
            if save_to_file:
                save_quiz_data(report, quiz_id, "report")
                qlogger.debug("Quiz report saved to file")

            if new_cursor:
                # Close the new cursor if it was created
                cursor.close()
                conn.close()

            return

        except (asyncio.TimeoutError, QueryCanceledError):
            retries += 1
            qlogger.warning(
                f"Operation timed out/cancelled for quiz report {quiz_id} (attempt {retries}/{max_retries})"
            )
            if retries == max_retries:
                qlogger.error(f"Max retries reached for updating quiz report {quiz_id}")
                raise
            wait_time = 2**retries
            await asyncio.sleep(wait_time)

        # Errors that require a new connection but not backoff
        except (psycopg2.InterfaceError, psycopg2.ProgrammingError):
            # Cursor is closed, get a new connection
            qlogger.warning(
                f"Cursor closed for quiz report {quiz_id} (attempt {retries + 1})"
            )
            cursor, conn = get_db_connection_no_context()
            new_cursor = True
            retries += 1
            if retries == max_retries:
                qlogger.error(
                    f"Max retries reached for updating quiz report {quiz_id}",
                    exc_info=True,
                )
                raise

        # For operational/database errors - add backoff
        except (psycopg2.OperationalError, psycopg2.DatabaseError) as e:
            retries += 1
            qlogger.error(
                f"Op/Db Error for quiz report {quiz_id}: {str(e)} - retry {retries}/{max_retries}"
            )
            if retries == max_retries:
                qlogger.error(f"Max retries reached for updating quiz report {quiz_id}")
                raise
            wait_time = 2**retries  # Add exponential backoff for these errors
            await asyncio.sleep(wait_time)

        except Exception as e:
            retries += 1
            qlogger.error(
                f"Error updating quiz report {quiz_id}: {str(e)} - retry {retries}/{max_retries}"
            )
            if retries == max_retries:
                qlogger.error(f"Max retries reached for updating quiz report {quiz_id}")
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
