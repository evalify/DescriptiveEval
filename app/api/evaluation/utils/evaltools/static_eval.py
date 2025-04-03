"""This module contains functions to evaluate student responses"""

from typing import List


async def evaluate_mcq(
    student_answers: List[str], correct_answers: List[str], total_score: float
) -> float:
    if set(student_answers) == set(
        correct_answers
    ):  # TODO: Check if this is the correct way to compare
        return total_score
    else:
        return 0


async def evaluate_mcq_with_partial_marking(
    student_answers: List[str], correct_answers: List[str], total_score: float
) -> float:
    """
    Give Partial Marking for MCQs based on the number of correct answers selected by the student.
    """
    correct_count = 0
    for student_answer in student_answers:
        if student_answer in correct_answers:
            correct_count += 1
        else:
            return 0

    return round(total_score * (correct_count / len(correct_answers)), 2)


async def evaluate_true_false(
    student_answer: str, correct_answer: str, total_score: float
) -> float:
    if isinstance(correct_answer, list):
        correct_answer = correct_answer[0]
    if student_answer == correct_answer:
        return total_score
    else:
        return 0


async def direct_match(
    student_answer: str, correct_answer: str, strip=True, case_sensitive=False
) -> bool:
    if strip:
        student_answer = student_answer.strip()
        correct_answer = correct_answer.strip()
    if not case_sensitive:
        student_answer = student_answer.lower()
        correct_answer = correct_answer.lower()
    if student_answer == correct_answer:
        return True
    else:
        return False


async def fitb_static_scoring(
    student_answer: str,
    correct_answer: str,
    total_score: float,
    strip=True,
    case_sensitive=False,
) -> float:
    """
    Evaluate a student's answer by directly matching it against the correct answer(s).

    This function performs a direct comparison between the student's answer and the correct answer.
    It supports optional whitespace stripping and case-insensitive comparisons. In addition, it
    handles multiple correct answers provided as a comma-separated string. For each correct answer,
    if multiple acceptable values exist, they should be separated by the pipe ('|') character.

    Note: The Order of the answers matters. So if expected is "a,b" and the student answers "b,a" it will be
    considered wrong.

    Parameters:
      student_answer (str): The answer provided by the student.
      correct_answer (str): The expected answer(s). Multiple answers should be comma-separated.
                            Within each answer, acceptable alternatives can be provided separated by '|'.
      total_score (float): The total score to be awarded for a completely correct answer.
      strip (bool, optional): If True, removes leading and trailing whitespace from answers. Defaults to True.
      case_sensitive (bool, optional): If False, comparison is performed in a case-insensitive manner. Defaults to False.

    Returns:
      float: The score awarded for the student answer, which is proportional to the number of correct matches.
             Returns total_score for an exact match, a proportional score (rounded to 2 decimal places) for
             partial matches, or 0 if no matches are found.
    """

    def strip_and_lower(text: str) -> str:
        if strip:
            text = text.strip()
        if not case_sensitive:
            text = text.lower()
        return text

    # Direct check - no parsing
    if strip_and_lower(student_answer) == strip_and_lower(correct_answer):
        return float(total_score)

    # Check for multiple correct answers
    correct_answers = (
        correct_answer.split(",") if "," in correct_answer else [correct_answer]
    )

    student_answers = (
        student_answer.split(",") if "," in student_answer else [student_answer]
    )

    correct_count = 0
    for idx, correct_option in enumerate(correct_answers):
        if idx >= len(student_answers):
            break

        # If the correct answer contains '|', split it and check if any part matches
        parts = correct_option.split("|") if "|" in correct_option else [correct_option]

        for part in parts:
            if strip_and_lower(student_answers[idx]) == strip_and_lower(part):
                correct_count += 1
                break

    return round(total_score * (correct_count / len(correct_answers)), 2)


if __name__ == "__main__":
    import asyncio

    # Test direct_match
    student_answer = "a, b, c"
    correct_answer = "a, b"
    expected_score = 2
    total_score = len(correct_answer.split(",")) or 1
    result = asyncio.run(
        fitb_static_scoring(student_answer, correct_answer, total_score)
    )
    print(
        f"Student Answer: {student_answer} Correct Answer: {correct_answer} Score: {result}"
    )
    assert result == float(expected_score), (
        f"Expected {expected_score}, but got {result}"
    )
