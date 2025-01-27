""""
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

from typing import Any, Dict, List
import json
import asyncio
import uuid

async def generate_quiz_report(quiz_id: str, quiz_results: List[Dict[str, Any]], questions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Generate a report for a quiz
    :param quiz_id: Quiz ID
    :param quiz_results: Results of the quiz
    :param questions: List of questions in the quiz
    :return: Quiz report
    """
    scores = [result['score'] for result in quiz_results]
    total_score = sum(scores)
    avg_score = total_score / len(scores)
    max_score = max(scores)
    min_score = min(scores)

    question_stats = []
    for question in questions:
        question_id = question['_id']
        correct = sum(1 for result in quiz_results if result['responses'].get(question_id,{}).get('score') == question['mark'])
        incorrect = len(quiz_results) - correct
        total_marks_obtained = sum(result['responses'].get(question_id,{}).get('score', 0) for result in quiz_results)
        question_stats.append({
            'questionId': question_id,
            'questionText': question['question'],
            'correct': correct,
            'incorrect': incorrect,
            'totalAttempts': correct + incorrect,
            'avgMarks': total_marks_obtained / len(quiz_results),
            'maxMarks': question['mark']
        })

    mark_distribution = {
        'excellent': sum(1 for score in scores if 80 <= score <= 100),
        'good': sum(1 for score in scores if 60 <= score <= 79),
        'average': sum(1 for score in scores if 40 <= score <= 59),
        'poor': sum(1 for score in scores if 0 <= score <= 39)
    }

    return {
        'quizId': quiz_id,
        'avgScore': avg_score,
        'maxScore': max_score,
        'minScore': min_score,
        'totalScore': total_score,
        'totalStudents': len(scores),
        'questionStats': question_stats,
        'markDistribution': mark_distribution
    }

async def save_quiz_report(quiz_id: str, report: Dict[str, Any], cursor, conn, save_to_file: bool = True) -> None:
    """
    Save the quiz report to the database and optionally to a file
    :param quiz_id: Quiz ID
    :param report: Quiz report data
    :param cursor: Database cursor
    :param conn: Database connection
    :param save_to_file: Whether to save to a file (default: True)
    """
    # Save to database
    await asyncio.to_thread(
        cursor.execute,
        """INSERT INTO "QuizReport" (
            "id", "quizId", "maxScore", "avgScore", "minScore", 
            "totalScore", "totalStudents", "questionStats", "markDistribution"
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT ("quizId") 
        DO UPDATE SET 
            "maxScore" = EXCLUDED."maxScore",
            "avgScore" = EXCLUDED."avgScore",
            "minScore" = EXCLUDED."minScore",
            "totalScore" = EXCLUDED."totalScore",
            "totalStudents" = EXCLUDED."totalStudents",
            "questionStats" = EXCLUDED."questionStats",
            "markDistribution" = EXCLUDED."markDistribution"
        """,
        (
            uuid.uuid4().hex,
            quiz_id,
            report['maxScore'],
            report['avgScore'],
            report['minScore'],
            report['totalScore'],
            report['totalStudents'],
            json.dumps(report['questionStats']),
            json.dumps(report['markDistribution'])
        )
    )
    await asyncio.to_thread(conn.commit)

    # Save to file if requested
    if save_to_file:
        try:
            with open(f'data/json/{quiz_id}_quiz_report.json', 'w') as f:
                json.dump(report, f, indent=4)
        except IOError as e:
            print(f"Error writing quiz report to file: {e}")