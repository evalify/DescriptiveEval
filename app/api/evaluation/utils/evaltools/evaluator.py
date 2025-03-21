"""
ResponseEvaluator class to handle evaluation of quiz responses.
This module contains the core evaluation logic that was previously in evaluation.py.
"""

import itertools
import threading
import json
from datetime import datetime
from typing import Optional, Dict, Any
from app.api.scoring.service import (
    get_llm,
    score,
    score_fill_in_blank,
    EvaluationStatus,
    LLMProvider,
)
from app.core.exceptions import (
    LLMEvaluationError,
    MCQEvaluationError,
    TrueFalseEvaluationError,
    CodingEvaluationError,
    FillInBlankEvaluationError,
    InvalidQuestionError,
)
from .code_eval import evaluate_coding_question
from .static_eval import (
    evaluate_mcq,
    evaluate_mcq_with_partial_marking,
    evaluate_true_false,
    direct_match,
)
from app.core.logger import QuizLogger
from app.config.constants import MAX_RETRIES
from app.utils.misc import remove_html_tags, save_quiz_data
from ..quiz.quiz_schema import QuizResponseSchema


class ResponseEvaluator:
    """
    Handles evaluation of a single quiz response.
    Designed to be extensible for parallel processing in the future.
    """

    def __init__(
        self, quiz_id: str, questions: list, evaluation_settings: Dict, llm=None
    ):
        self.quiz_id = quiz_id
        self.questions = {
            str(q["_id"]): q for q in questions
        }  # Convert to dict for O(1) lookup
        self.total_marks = sum(
            question.get("marks", question["mark"]) for question in questions
        )  # Questions are already validated before call in validate_quiz_setup

        self.evaluation_settings = evaluation_settings or {}
        self.llm = llm
        self.qlogger = QuizLogger(quiz_id)

        # Thread-safe metadata handling
        self._metadata_lock = threading.Lock()
        self.evaluation_metadata = {
            "quiz_id": quiz_id,
            "start_time": datetime.now().isoformat(),
            "settings": evaluation_settings,
            "aggregates": {
                "total_questions": len(questions),
                "question_types": {},
                "llm_usage": {"total_calls": 0, "total_duration": 0, "providers": {}},
                "errors": {"total": 0, "by_type": {}},
            },
            "responses": {},
        }

        # Thread-safe LLM key rotation
        self._llm_lock = threading.Lock()
        if llm is None:
            self.qlogger.info(
                "No LLM instance provided. Using default Groq API key rotation"
            )
            import os

            keys = [
                os.getenv(f"GROQ_API_KEY{i if i > 1 else ''}", None)
                for i in range(1, 6)
            ]
            self.valid_keys = [key for key in keys if key]
            if not self.valid_keys:
                raise ValueError("No valid API keys found for evaluation")
            self._key_iter = itertools.cycle(self.valid_keys)
            self.qlogger.info(
                f"Using {len(self.valid_keys)} API keys in rotation for evaluation"
            )

        # Extract settings
        self.negative_marking = self.evaluation_settings.get("negativeMark", False)
        self.mcq_partial_marking = self.evaluation_settings.get("mcqPartialMark", True)
        self.coding_partial_marking = self.evaluation_settings.get(
            "codePartialMark", True
        )

    def _get_next_api_key(self):
        """Thread-safe API key rotation"""
        with self._llm_lock:
            return next(self._key_iter)

    def _update_llm_stats(self, provider: str, duration: float):
        """Thread-safe LLM statistics update"""
        with self._metadata_lock:
            self.evaluation_metadata["aggregates"]["llm_usage"]["total_calls"] += 1
            self.evaluation_metadata["aggregates"]["llm_usage"]["total_duration"] += (
                duration
            )
            if (
                provider
                not in self.evaluation_metadata["aggregates"]["llm_usage"]["providers"]
            ):
                self.evaluation_metadata["aggregates"]["llm_usage"]["providers"][
                    provider
                ] = {"calls": 0, "total_duration": 0}
            self.evaluation_metadata["aggregates"]["llm_usage"]["providers"][provider][
                "calls"
            ] += 1
            self.evaluation_metadata["aggregates"]["llm_usage"]["providers"][provider][
                "total_duration"
            ] += duration

    def _update_error_stats(self, error_type: str):
        """Thread-safe error statistics update"""
        with self._metadata_lock:
            self.evaluation_metadata["aggregates"]["errors"]["total"] += 1
            if (
                error_type
                not in self.evaluation_metadata["aggregates"]["errors"]["by_type"]
            ):
                self.evaluation_metadata["aggregates"]["errors"]["by_type"][
                    error_type
                ] = 0
            self.evaluation_metadata["aggregates"]["errors"]["by_type"][error_type] += 1

    def _save_metadata(self):
        """Save evaluation metadata to file with final aggregates"""
        end_time = datetime.now()
        with self._metadata_lock:
            self.evaluation_metadata.update(
                {
                    "end_time": end_time.isoformat(),
                    "total_duration": (
                        end_time
                        - datetime.fromisoformat(self.evaluation_metadata["start_time"])
                    ).total_seconds(),
                    "aggregates": {
                        **self.evaluation_metadata["aggregates"],
                        "success_rate": {
                            "total": sum(
                                1
                                for r in self.evaluation_metadata["responses"].values()
                                for q in r.values()
                                if isinstance(q, dict)
                                and q.get("evaluationStatus")
                                == EvaluationStatus.SUCCESS.value
                            ),
                            "by_type": {},
                        },
                    },
                }
            )

            # Calculate success rates by question type
            for q_type in self.evaluation_metadata["aggregates"]["question_types"]:
                successes = sum(
                    1
                    for r in self.evaluation_metadata["responses"].values()
                    for q in r.values()
                    if isinstance(q, dict)
                    and q.get("questionType") == q_type
                    and q.get("evaluationStatus") == EvaluationStatus.SUCCESS.value
                )
                total = self.evaluation_metadata["aggregates"]["question_types"][q_type]
                self.evaluation_metadata["aggregates"]["success_rate"]["by_type"][
                    q_type
                ] = {
                    "success": successes,
                    "total": total,
                    "rate": successes / total if total > 0 else 0,
                }

            save_quiz_data(
                self.evaluation_metadata, self.quiz_id, "evaluation_metadata"
            )

    def _update_response_metadata(
        self, response_id: str, question_id: str, metadata: dict
    ):
        """Thread-safe metadata update"""
        with self._metadata_lock:
            if response_id not in self.evaluation_metadata["responses"]:
                self.evaluation_metadata["responses"][response_id] = {}
            if question_id not in self.evaluation_metadata["responses"][response_id]:
                self.evaluation_metadata["responses"][response_id][question_id] = {}

            self.evaluation_metadata["responses"][response_id][question_id].update(
                metadata
            )

    async def evaluate_response(
        self,
        quiz_result: Dict[str, Any],
        types_to_evaluate: Optional[Dict[str, bool]] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate a single quiz response.

        Args:
            quiz_result: The quiz response to evaluate
            types_to_evaluate: Dictionary of question types to evaluate

        Returns:
            Updated quiz_result with evaluation scores and metadata
        """
        if not types_to_evaluate:
            types_to_evaluate = {
                "MCQ": True,
                "DESCRIPTIVE": True,
                "CODING": True,
                "TRUE_FALSE": True,
                "FILL_IN_BLANK": True,
            }

        response_id = quiz_result["id"]
        with self._metadata_lock:
            self.evaluation_metadata["responses"][response_id] = {
                "student_id": quiz_result.get("studentId"),
                "start_time": datetime.now().isoformat(),
                "questions": {},
            }

        self.qlogger.info(
            f"Evaluating response {quiz_result['id']} for student {quiz_result['studentId']}"
        )
        quiz_result["totalScore"] = self.total_marks
        # quiz_result["score"] = 0

        for qid, question in self.questions.items():
            # Handle old schema conversion
            if isinstance(quiz_result["responses"].get(qid), list):
                quiz_result["responses"][qid] = {
                    "student_answer": quiz_result["responses"][qid],
                }
                if "questionMarks" in quiz_result:
                    del quiz_result["questionMarks"]

            # Set total score for question
            try:
                if question.get("marks") is not None:
                    question["mark"] = question["marks"]
                question_total_score = question["mark"]
            except KeyError:
                raise InvalidQuestionError(
                    f"Question {qid} is missing required 'mark'/'marks' attribute"
                )

            # Skip question if no response found
            if qid not in quiz_result["responses"]:
                self.qlogger.warning(f"No response found for question {qid}")
                continue

            question_type = question.get("type", "").upper()

            # Skip question if its type is not in types_to_evaluate
            if not types_to_evaluate.get(
                question_type, types_to_evaluate.get(question_type.lower(), True)
            ):
                self.qlogger.info(
                    f"Skipping evaluation for question {qid} of type {question_type}"
                )
                continue

            # Evaluate question based on type
            try:
                evaluation_metadata = {
                    "evaluatedAt": datetime.now().isoformat(),
                    "questionType": question_type,
                    "evaluationAttempts": 0,
                }

                await self._evaluate_question(
                    quiz_result,
                    qid,
                    question,
                    evaluation_metadata,
                    question_total_score,
                )

            except Exception as e:
                self.qlogger.error(
                    f"Error evaluating question {qid}: {str(e)}", exc_info=True
                )
                raise

        # Calculate total score including negative marking
        quiz_result["score"] = max(
            sum(
                [
                    (QuizResponseSchema.get_attribute(quiz_result, qid, "score") or 0)
                    + (
                        QuizResponseSchema.get_attribute(
                            quiz_result, qid, "negative_score"
                        )
                        or 0
                    )
                    for qid in quiz_result["responses"].keys()
                ]
            ),
            0,
        )

        # Save metadata at the end
        self._save_metadata()
        return quiz_result

    async def _evaluate_question(
        self,
        quiz_result: Dict[str, Any],
        qid: str,
        question: Dict[str, Any],
        evaluation_metadata: Dict[str, Any],
        question_total_score: float,
    ):
        """Evaluate a single question within a response."""
        response_id = quiz_result["id"]
        question_type = question.get("type", "").upper()
        self.qlogger.debug(f"Evaluating question {qid} of type {question_type}")

        # Initialize evaluation metadata
        evaluation_metadata = {
            "evaluatedAt": datetime.now().isoformat(),
            "questionType": question_type,
            "evaluationAttempts": 0,
        }
        self._update_response_metadata(response_id, qid, evaluation_metadata)

        match question_type:
            case "MCQ":
                await self._evaluate_mcq(
                    quiz_result,
                    qid,
                    question,
                    question_total_score,
                )

            case "DESCRIPTIVE":
                await self._evaluate_descriptive(
                    quiz_result,
                    qid,
                    question,
                    question_total_score,
                )

            case "CODING":
                await self._evaluate_coding(
                    quiz_result,
                    qid,
                    question,
                    question_total_score,
                    evaluation_metadata,
                )

            case "TRUE_FALSE":
                await self._evaluate_true_false(
                    quiz_result,
                    qid,
                    question,
                    question_total_score,
                    evaluation_metadata,
                )

            case "FILL_IN_BLANK":
                await self._evaluate_fill_in_blank(
                    quiz_result,
                    qid,
                    question,
                    question_total_score,
                    evaluation_metadata,
                )

            case _:
                self.qlogger.warning(
                    f"Unhandled question type: {question_type!r} for question {qid}"
                )

    async def _evaluate_mcq(self, quiz_result, qid, question, question_total_score):
        """Evaluate MCQ type question"""
        response_id = quiz_result["id"]
        start_time = datetime.now()

        student_answers = QuizResponseSchema.get_attribute(
            quiz_result, qid, "student_answer"
        )
        if not student_answers:
            self.qlogger.warning(f"Empty response for MCQ question {qid}")
            QuizResponseSchema.set_attribute(quiz_result, qid, "score", 0)
            QuizResponseSchema.set_attribute(
                quiz_result, qid, "remarks", "No answer provided"
            )
            self._update_response_metadata(
                response_id,
                qid,
                {
                    "evaluationStatus": EvaluationStatus.EMPTY_ANSWER.value,
                    "evaluationMethod": "auto",
                    "duration": (datetime.now() - start_time).total_seconds(),
                },
            )
            return

        correct_answers = question.get("answer")
        if not correct_answers:
            raise InvalidQuestionError(f"Question {qid} is missing correct answer")

        try:
            if self.mcq_partial_marking:
                mcq_score = await evaluate_mcq_with_partial_marking(
                    student_answers, correct_answers, question_total_score
                )
            else:
                mcq_score = await evaluate_mcq(
                    student_answers, correct_answers, question_total_score
                )

            QuizResponseSchema.set_attribute(quiz_result, qid, "score", mcq_score)
            neg_score = None
            if self.negative_marking and mcq_score <= 0:
                neg_score = question.get("negativeMark", -question_total_score / 2)
                QuizResponseSchema.set_attribute(
                    quiz_result, qid, "negative_score", neg_score
                )

            self._update_response_metadata(
                response_id,
                qid,
                {
                    "evaluationStatus": EvaluationStatus.SUCCESS.value,
                    "evaluationMethod": "auto",
                    "duration": (datetime.now() - start_time).total_seconds(),
                    "partialMarking": self.mcq_partial_marking,
                    "negativeMarking": True if neg_score else False,
                },
            )
        except Exception as e:
            self.qlogger.error(
                f"MCQ evaluation failed for question {qid}", exc_info=True
            )
            self._update_response_metadata(
                response_id,
                qid,
                {
                    "evaluationStatus": EvaluationStatus.PARSE_ERROR.value,
                    "evaluationMethod": "auto",
                    "duration": (datetime.now() - start_time).total_seconds(),
                    "error": str(e),
                },
            )
            self._update_error_stats("MCQ_ERROR")
            raise MCQEvaluationError(qid, student_answers, correct_answers)

    async def _evaluate_descriptive(
        self, quiz_result, qid, question, question_total_score
    ):
        """Evaluate descriptive type question"""
        # response_id = quiz_result["id"]
        clean_question = remove_html_tags(question["question"]).strip()
        student_answer = QuizResponseSchema.get_attribute(
            quiz_result, qid, "student_answer"
        )[0]
        if await direct_match(
            student_answer, question["expectedAnswer"], strip=True, case_sensitive=False
        ):
            score_res = {
                "score": question_total_score,
                "reason": "Exact Match",
                "rubric": "Exact Match - LLM not used",
                "breakdown": "Exact Match - LLM not used",
                "status": EvaluationStatus.SUCCESS,
            }
            # self._update_response_metadata(
            #     response_id,
            #     qid,
            #     {
            #         "evaluationStatus": EvaluationStatus.SUCCESS.value,
            #         "evaluationMethod": "exact_match",
            #         "duration": 0,
            #     },
            # )
        else:
            # start_time = datetime.now()
            current_llm = (
                self.llm
                if self.llm
                else get_llm(LLMProvider.GROQ, self._get_next_api_key())
            )
            errors = []
            last_response = None
            attempt = 0
            for attempt in range(MAX_RETRIES):
                try:
                    score_res = await score(
                        llm=current_llm,
                        question=clean_question,
                        student_ans=student_answer,
                        expected_ans=question["expectedAnswer"],
                        guidelines=question["guidelines"],
                        total_score=question_total_score,
                    )
                    last_response = score_res

                    # Break immediately for client-side errors
                    if score_res.get("status") in [
                        EvaluationStatus.INVALID_INPUT,
                        EvaluationStatus.EMPTY_ANSWER,
                    ]:
                        # self._update_error_stats("INVALID_INPUT")
                        break

                    # Continue retrying for server-side errors
                    if score_res.get("status") == EvaluationStatus.SUCCESS:
                        break

                    errors.append(score_res.get("error", "Unknown error"))
                    # self._update_error_stats("LLM_ERROR")

                except Exception as e:
                    errors.append(str(e))
                    # self._update_error_stats("LLM_EXCEPTION")
                    if attempt == MAX_RETRIES - 1:
                        raise LLMEvaluationError(qid, errors)
                    if not self.llm:
                        current_llm = get_llm(
                            LLMProvider.GROQ, self._get_next_api_key()
                        )

            score_res = last_response
            if not score_res or score_res.get("status") != EvaluationStatus.SUCCESS:
                if not score_res:
                    score_res = {
                        "score": 0,
                        "reason": f"Multiple evaluation attempts failed: {', '.join(errors)}",
                        "rubric": "Evaluation failed after maximum retries",
                        "breakdown": "Evaluation failed after maximum retries",
                        "status": EvaluationStatus.LLM_ERROR,
                    }

            # self._update_response_metadata(
            #     response_id,
            #     qid,
            #     {
            #         "evaluationStatus": score_res.get(
            #             "status", EvaluationStatus.LLM_ERROR
            #         ).value,
            #         "evaluationMethod": "llm",
            #         "llmProvider": current_llm.__class__.__name__,
            #         "evaluationAttempts": attempt + 1 if "attempt" in locals() else 0,
            #         "errors": errors if errors else None,
            #         "duration": (datetime.now() - start_time).total_seconds(),
            #     },
            # )
            # self._update_llm_stats(
            #     current_llm.__class__.__name__,
            #     (datetime.now() - start_time).total_seconds(),
            # )

        QuizResponseSchema.set_attribute(quiz_result, qid, "score", score_res["score"])
        QuizResponseSchema.set_attribute(
            quiz_result, qid, "remarks", score_res["reason"]
        )
        QuizResponseSchema.set_attribute(
            quiz_result,
            qid,
            "breakdown",
            score_res.get("breakdown", "No breakdown available"),
        )

    async def _evaluate_coding(
        self, quiz_result, qid, question, question_total_score, evaluation_metadata
    ):
        """Evaluate coding type question"""
        response_id = quiz_result["id"]
        start_time = datetime.now()

        response = QuizResponseSchema.get_attribute(quiz_result, qid, "student_answer")
        if not response:
            self.qlogger.warning(f"Empty response for coding question {qid}")
            QuizResponseSchema.set_attribute(quiz_result, qid, "score", 0)
            QuizResponseSchema.set_attribute(
                quiz_result, qid, "remarks", "No code submitted"
            )
            self._update_response_metadata(
                response_id,
                qid,
                {
                    "evaluationStatus": EvaluationStatus.EMPTY_ANSWER.value,
                    "evaluationMethod": "auto",
                    "duration": (datetime.now() - start_time).total_seconds(),
                },
            )
            return

        response = json.loads(response[0])
        response = response[0]  # It's nested AGAIN!!

        driver_code = question.get("driverCode")
        test_cases = question.get("testCases", [])
        if not driver_code or not test_cases:
            raise InvalidQuestionError(
                f"Question {qid} is missing driver code or test cases"
            )

        try:
            (
                coding_passed_cases,
                coding_total_cases,
                eval_result,
            ) = await evaluate_coding_question(
                student_response=response.get("content"),
                language=response.get("language"),
                driver_code=driver_code,
                test_cases_count=len(test_cases),
            )

            if self.coding_partial_marking:
                coding_score = round(
                    (coding_passed_cases / (coding_total_cases)) * question_total_score,
                    2,
                )
            else:
                coding_score = (
                    question_total_score
                    if coding_passed_cases == coding_total_cases
                    else 0
                )

            QuizResponseSchema.set_attribute(quiz_result, qid, "score", coding_score)
            QuizResponseSchema.set_attribute(quiz_result, qid, "remarks", eval_result)

            self._update_response_metadata(
                response_id,
                qid,
                {
                    "evaluationStatus": EvaluationStatus.SUCCESS.value,
                    "evaluationMethod": "test_cases",
                    "duration": (datetime.now() - start_time).total_seconds(),
                    "testCasesCount": len(test_cases),
                    "testCasesResult": eval_result,
                },
            )
        except Exception as e:
            self.qlogger.error(
                f"Coding evaluation failed for question {qid}", exc_info=True
            )
            self._update_response_metadata(
                response_id,
                qid,
                {
                    "evaluationStatus": EvaluationStatus.PARSE_ERROR.value,
                    "evaluationMethod": "test_cases",
                    "duration": (datetime.now() - start_time).total_seconds(),
                    "error": str(e),
                    "testCasesCount": len(test_cases),
                },
            )
            self._update_error_stats("CODING_ERROR")
            raise CodingEvaluationError(qid, str(e), len(test_cases))

    async def _evaluate_true_false(
        self, quiz_result, qid, question, question_total_score, evaluation_metadata
    ):
        """Evaluate true/false type question"""
        response_id = quiz_result["id"]
        start_time = datetime.now()

        response = QuizResponseSchema.get_attribute(quiz_result, qid, "student_answer")
        if not response:
            self.qlogger.warning(f"Empty response for True/False question {qid}")
            QuizResponseSchema.set_attribute(quiz_result, qid, "score", 0)
            QuizResponseSchema.set_attribute(
                quiz_result, qid, "remarks", "No answer provided"
            )
            self._update_response_metadata(
                response_id,
                qid,
                {
                    "evaluationStatus": EvaluationStatus.EMPTY_ANSWER.value,
                    "evaluationMethod": "auto",
                    "duration": (datetime.now() - start_time).total_seconds(),
                },
            )
            return

        correct_answer = question.get("answer")
        if correct_answer is None:
            raise InvalidQuestionError(f"Question {qid} is missing correct answer")

        try:
            tf_score = await evaluate_true_false(
                response[0], correct_answer, question_total_score
            )
            QuizResponseSchema.set_attribute(quiz_result, qid, "score", tf_score)
            neg_score = None
            if self.negative_marking and tf_score <= 0:
                neg_score = question.get("negativeMark", -question_total_score / 2)
                QuizResponseSchema.set_attribute(
                    quiz_result, qid, "negative_score", neg_score
                )

            self._update_response_metadata(
                response_id,
                qid,
                {
                    "evaluationStatus": EvaluationStatus.SUCCESS.value,
                    "evaluationMethod": "auto",
                    "duration": (datetime.now() - start_time).total_seconds(),
                    "negativeMarking": True if neg_score else False,
                },
            )
        except Exception as e:
            self.qlogger.error(
                f"True/False evaluation failed for question {qid}", exc_info=True
            )
            self._update_response_metadata(
                response_id,
                qid,
                {
                    "evaluationStatus": EvaluationStatus.PARSE_ERROR.value,
                    "evaluationMethod": "auto",
                    "duration": (datetime.now() - start_time).total_seconds(),
                    "error": str(e),
                },
            )
            self._update_error_stats("TRUE_FALSE_ERROR")
            raise TrueFalseEvaluationError(qid, response[0], correct_answer)

    async def _evaluate_fill_in_blank(
        self, quiz_result, qid, question, question_total_score, evaluation_metadata
    ):
        """Evaluate fill in blank type question"""
        response_id = quiz_result["id"]
        start_time = datetime.now()

        response = QuizResponseSchema.get_attribute(quiz_result, qid, "student_answer")[
            0
        ]
        if not response:
            self.qlogger.warning(f"Empty response for fill in blank question {qid}")
            QuizResponseSchema.set_attribute(quiz_result, qid, "score", 0)
            QuizResponseSchema.set_attribute(
                quiz_result, qid, "remarks", "No answer provided"
            )
            self._update_response_metadata(
                response_id,
                qid,
                {
                    "evaluationStatus": EvaluationStatus.EMPTY_ANSWER.value,
                    "evaluationMethod": "exact_match",
                    "duration": (datetime.now() - start_time).total_seconds(),
                },
            )
            return

        correct_answer = question.get("expectedAnswer")
        if not correct_answer:
            raise InvalidQuestionError(f"Question {qid} is missing expected answer")

        if await direct_match(
            response, correct_answer, strip=True, case_sensitive=False
        ):
            fitb_score = {
                "score": question_total_score,
                "reason": "Exact Match",
                "status": EvaluationStatus.SUCCESS,
            }
            self._update_response_metadata(
                response_id,
                qid,
                {
                    "evaluationStatus": EvaluationStatus.SUCCESS.value,
                    "evaluationMethod": "exact_match",
                    "duration": (datetime.now() - start_time).total_seconds(),
                },
            )
        else:
            llm_start_time = datetime.now()
            current_llm = (
                self.llm
                if self.llm
                else get_llm(LLMProvider.GROQ, self._get_next_api_key())
            )
            clean_question = remove_html_tags(question["question"]).strip()

            evaluation_attempts = []
            last_response = None
            attempt = 0
            for attempt in range(MAX_RETRIES):
                try:
                    fitb_score = await score_fill_in_blank(
                        llm=current_llm,
                        question=clean_question,
                        student_ans=response,
                        expected_ans=correct_answer,
                        total_score=question_total_score,
                    )
                    last_response = fitb_score

                    # Break immediately for client-side errors
                    if fitb_score.get("status") in [
                        EvaluationStatus.INVALID_INPUT,
                        EvaluationStatus.EMPTY_ANSWER,
                    ]:
                        self._update_error_stats("INVALID_INPUT")
                        break

                    # Continue retrying for server-side errors
                    if fitb_score.get("status") == EvaluationStatus.SUCCESS:
                        break

                    evaluation_attempts.append(fitb_score.get("error", "Unknown error"))
                    self._update_error_stats("LLM_ERROR")

                except Exception as e:
                    evaluation_attempts.append(str(e))
                    self._update_error_stats("LLM_EXCEPTION")
                    if attempt == MAX_RETRIES - 1:
                        raise FillInBlankEvaluationError(
                            qid, evaluation_attempts, MAX_RETRIES
                        )
                    current_llm = get_llm(LLMProvider.GROQ, self._get_next_api_key())

            fitb_score = last_response
            if not fitb_score or fitb_score.get("status") != EvaluationStatus.SUCCESS:
                if not fitb_score:
                    fitb_score = {
                        "score": 0,
                        "reason": f"Multiple evaluation attempts failed: {', '.join(evaluation_attempts)}",
                        "status": EvaluationStatus.LLM_ERROR,
                    }

            self._update_response_metadata(
                response_id,
                qid,
                {
                    "evaluationStatus": fitb_score.get(
                        "status", EvaluationStatus.LLM_ERROR
                    ).value,
                    "evaluationMethod": "llm",
                    "llmProvider": current_llm.__class__.__name__,
                    "evaluationAttempts": attempt + 1 if "attempt" in locals() else 0,
                    "errors": evaluation_attempts if evaluation_attempts else None,
                    "evaluationErrors": evaluation_attempts
                    if evaluation_attempts
                    else None,
                    "duration": {
                        "total": (datetime.now() - start_time).total_seconds(),
                        "llm": (datetime.now() - llm_start_time).total_seconds(),
                    },
                },
            )
            self._update_llm_stats(
                current_llm.__class__.__name__,
                (datetime.now() - llm_start_time).total_seconds(),
            )

        QuizResponseSchema.set_attribute(quiz_result, qid, "score", fitb_score["score"])
        QuizResponseSchema.set_attribute(
            quiz_result, qid, "remarks", fitb_score["reason"]
        )
