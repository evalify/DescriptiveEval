"""Test fixtures for evaluation tests"""

mock_questions = [
    {
        "_id": "q1",
        "quizId": "test-quiz-123",
        "type": "MCQ",
        "question": "What is the capital of France?",
        "options": ["London", "Paris", "Berlin", "Madrid"],
        "answer": ["Paris"],
        "mark": 1,
        "negativeMark": -0.25,
    },
    {
        "_id": "q2",
        "quizId": "test-quiz-123",
        "type": "DESCRIPTIVE",
        "question": "Explain the process of photosynthesis.",
        "expectedAnswer": "Photosynthesis is the process by which plants convert light energy into chemical energy to produce glucose using carbon dioxide and water.",
        "mark": 5,
        "guidelines": "Evaluate based on: 1) Understanding of energy conversion 2) Mention of required materials 3) Accuracy of process description",
    },
    {
        "_id": "q3",
        "quizId": "test-quiz-123",
        "type": "TRUE_FALSE",
        "question": "Python is a compiled language.",
        "answer": ["False"],
        "mark": 1,
        "negativeMark": -0.25,
    },
    {
        "_id": "q4",
        "quizId": "test-quiz-123",
        "type": "FILL_IN_BLANK",
        "question": "The Earth revolves around the ________.",
        "expectedAnswer": "Sun",
        "mark": 1,
    },
    {
        "_id": "q5",
        "quizId": "test-quiz-123",
        "type": "CODING",
        "question": "Write a function to calculate factorial of a number.",
        "expectedAnswer": "",
        "driverCode": """def test_factorial(func):
    assert func(0) == 1
    assert func(1) == 1
    assert func(5) == 120
    return True""",
        "testcases": [
            {"input": "0", "expected": "1"},
            {"input": "1", "expected": "1"},
            {"input": "5", "expected": "120"},
        ],
        "mark": 5,
        "language": "python",
    },
]

mock_responses = [
    {
        "id": "r1",
        "studentId": "student1",
        "quizId": "test-quiz-123",
        "score": 0,  # Will be calculated during evaluation
        "submittedAt": "2025-01-07 10:25:44.442000",
        "responses": {
            "q1": {"student_answer": ["Paris"]},
            "q2": {
                "student_answer": [
                    "Photosynthesis is the process where plants convert sunlight into energy and make food."
                ]
            },
            "q3": {"student_answer": ["True"]},
            "q4": {"student_answer": ["Sun"]},
            "q5": {
                "student_answer": [
                    """def factorial(n):
    if n == 0 or n == 1:
        return 1
    return n * factorial(n-1)"""
                ]
            },
        },
        "violations": "",
        "totalScore": 13.0,  # Sum of all question marks
        "isEvaluated": "UNEVALUATED",
    },
    {
        "id": "r2",
        "studentId": "student2",
        "quizId": "test-quiz-123",
        "score": 0,  # Will be calculated during evaluation
        "submittedAt": "2025-01-07 10:30:12.123000",
        "responses": {
            "q1": {"student_answer": ["London"]},
            "q2": {
                "student_answer": [
                    "Photosynthesis is when plants make their own food using sunlight."
                ]
            },
            "q3": {"student_answer": ["False"]},
            "q4": {"student_answer": ["moon"]},
            "q5": {
                "student_answer": [
                    """def factorial(n):
    result = 1
    for i in range(1, n+1):
        result *= i
    return result"""
                ]
            },
        },
        "violations": "",
        "totalScore": 13.0,
        "isEvaluated": "UNEVALUATED",
    },
]

mock_evaluation_settings = {"negativeMark": True, "mcqPartialMark": True}
