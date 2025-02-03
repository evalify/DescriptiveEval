"""Custom exceptions for the evaluation system"""

class EvaluationError(Exception):
    """Base class for evaluation related exceptions"""
    pass

class NoQuestionsError(EvaluationError):
    """Raised when no questions are found for a quiz"""
    pass

class NoResponsesError(EvaluationError):
    """Raised when no responses are found for a quiz"""
    pass

class LLMEvaluationError(EvaluationError):
    """Raised when LLM evaluation fails after all retries"""
    pass

class InvalidQuestionError(EvaluationError):
    """Raised when a question is missing required attributes"""
    pass

class FillInBlankEvaluationError(EvaluationError):
    """Raised when fill in the blank evaluation fails"""
    def __init__(self, question_id: str, attempts: list, max_retries: int):
        self.attempts = attempts
        super().__init__(
            f"Fill in the blank evaluation failed after {max_retries} attempts for question {question_id}.\n"
            f"Attempt details:\n" + "\n".join(
                f"Attempt {i+1}: {attempt['error']}" 
                for i, attempt in enumerate(attempts)
            )
        )

class MCQEvaluationError(EvaluationError):
    """Raised when MCQ evaluation encounters an error"""
    def __init__(self, question_id: str, student_answer: any, correct_answer: any):
        super().__init__(
            f"MCQ evaluation failed for question {question_id}.\n"
            f"Student answer: {student_answer}\n"
            f"Correct answer: {correct_answer}\n"
            "Possible causes:\n"
            "- Answer format mismatch\n"
            "- Invalid answer options\n"
            "- Missing or malformed answer data"
        )

class TrueFalseEvaluationError(EvaluationError):
    """Raised when True/False evaluation encounters an error"""
    def __init__(self, question_id: str, student_answer: any, correct_answer: any):
        super().__init__(
            f"True/False evaluation failed for question {question_id}.\n"
            f"Student answer: {student_answer}\n"
            f"Correct answer: {correct_answer}\n"
            "Expected boolean or boolean-like values (true/false, 0/1, yes/no)"
        )

class CodingEvaluationError(EvaluationError):
    """Raised when coding question evaluation fails"""
    def __init__(self, question_id: str, error_msg: str, test_cases: int):
        super().__init__(
            f"Coding evaluation failed for question {question_id}.\n"
            f"Error: {error_msg}\n"
            f"Number of test cases: {test_cases}\n"
            "Possible causes:\n"
            "- Syntax error in student code\n"
            "- Runtime error in execution\n"
            "- Timeout during evaluation\n"
            "- Missing or invalid test cases"
        )

class TotalScoreError(EvaluationError):
    """Raised when there are issues with quiz total scores"""
    def __init__(self, quiz_id: str, scores: set, inconsistency_type: str):
        self.scores = scores
        super().__init__(
            f"Total score error in quiz {quiz_id}.\n"
            f"Type: {inconsistency_type}\n"
            f"Found scores: {scores}\n"
            "This could indicate:\n"
            "- Incomplete quiz configuration\n"
            "- Data corruption\n"
            "- Concurrent modifications to quiz settings"
        )

class DatabaseConnectionError(EvaluationError):
    """Raised when database operations fail"""
    pass

class ResponseQuestionMismatchError(EvaluationError):
    """Raised when response contains question IDs that don't exist in quiz questions"""
    def __init__(self, quiz_id: str, invalid_questions: set):
        self.invalid_questions = invalid_questions
        super().__init__(
            f"Response contains invalid question IDs for quiz {quiz_id}.\n"
            f"Invalid question IDs: {sorted(invalid_questions)}\n"
            "This could indicate:\n"
            "- Data corruption in responses\n"
            "- Questions were removed from quiz after responses were submitted\n"
            "- Database synchronization issues between questions and responses"
        )

class InvalidProviderError(EvaluationError):
    """Raised when an invalid LLM provider is specified"""
    def __init__(self, provider: str):
        super().__init__(
            f"Invalid LLM provider specified: {provider}.\n"
            "Supported providers are: 'ollama', 'groq'."
        )

class InvalidInputError(EvaluationError):
    """Raised when invalid input parameters are provided"""
    def __init__(self, parameter: str, value: any):
        super().__init__(
            f"Invalid input parameter: {parameter} with value: {value}.\n"
            "Please provide valid input parameters."
        )

class EmptyAnswerError(EvaluationError):
    """Raised when the student's answer is empty or missing"""
    def __init__(self):
        super().__init__(
            "Student answer is empty or missing.\n"
            "Please provide a valid answer."
        )

class InvalidQuizIDError(EvaluationError):
    """Raised when an invalid quiz ID is provided"""
    def __init__(self, quiz_id: str):
        super().__init__(
            f"Invalid quiz ID provided: {quiz_id}.\n"
            "Please provide a valid quiz ID."
        )

class EmptyQuizError(EvaluationError):
    """Raised when the quiz is empty"""
    def __init__(self):
        super().__init__(
            "The quiz is empty.\n"
            "Please provide a quiz with questions and responses."
        )
