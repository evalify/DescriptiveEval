async def evaluate_mcq(student_answers, correct_answers, total_score):
    if set(student_answers) == set(correct_answers):  # TODO: Check if this is the correct way to compare
        return total_score
    else:
        return 0


async def evaluate_true_false(student_answer, correct_answer, total_score):
    if student_answer == correct_answer:
        return total_score
    else:
        return 0
