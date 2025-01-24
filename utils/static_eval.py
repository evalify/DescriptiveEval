async def evaluate_mcq(student_answers: str, correct_answers: str, total_score: float) -> float:
    if set(student_answers) == set(correct_answers):  # TODO: Check if this is the correct way to compare
        return total_score
    else:
        return 0


async def evaluate_true_false(student_answer: str, correct_answer: str, total_score: float) -> float:
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
