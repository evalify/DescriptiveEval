"""This module contains functions to evaluate student responses"""

from typing import List

async def evaluate_mcq(student_answers: List[str], correct_answers: List[str], total_score: float) -> float:
    if set(student_answers) == set(correct_answers):  # TODO: Check if this is the correct way to compare
        return total_score
    else:
        return 0

async def evaluate_mcq_with_partial_marking(student_answers: List[str], correct_answers: List[str], total_score: float) -> float:
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
    

async def evaluate_true_false(student_answer: str, correct_answer: str, total_score: float) -> float:
    if isinstance(correct_answer, list):
        correct_answer = correct_answer[0]
    if student_answer == correct_answer:
        return total_score
    else:
        return 0


async def direct_match(student_answer: str, correct_answer: str, strip=True,
                       case_sensitive=False) -> bool:
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
