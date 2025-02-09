"""Module for detailed evaluation logging in JSON format"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Union

class EvaluationLogger:
    """Handles detailed JSON logging of quiz evaluations with type-specific question handling"""
    
    def __init__(self, quiz_id: str):
        self.quiz_id = quiz_id
        self.log_dir = Path(f"data/json/{quiz_id}")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / "evaluation_log.json"
        self.evaluation_data: Dict[str, Dict] = {}
        
        # Load existing data if file exists
        if self.log_file.exists():
            try:
                with open(self.log_file, 'r') as f:
                    self.evaluation_data = json.load(f)
            except json.JSONDecodeError:
                pass
    
    def _get_question_answer(self, question_data: Dict[str, Any], question_type: str) -> Union[str, list, None]:
        """Safely extracts the answer based on the question type"""
        if question_type == "MCQ":
            return question_data.get("answer", [])  # List of correct option IDs
        elif question_type == "TRUE_FALSE":
            return question_data.get("answer", [])  # List with single correct option ID
        elif question_type in ["DESCRIPTIVE", "FILL_IN_BLANK"]:
            return question_data.get("expectedAnswer")  # String expected answer
        elif question_type == "CODING":
            # For coding, we might want both driver code and test cases
            return {
                "driverCode": question_data.get("driverCode"),
                "testcases": question_data.get("testcases", [])
            }
        return None

    def _get_question_data(self, question_data: Dict[str, Any]) -> Dict[str, Any]:
        """Safely extract question data with type-specific handling"""
        question_type = question_data.get("type", "").upper()
        
        base_data = {
            "id": str(question_data.get("_id", "")),
            "type": question_type,
            "text": question_data.get("question", ""),
            "mark": question_data.get("mark") or question_data.get("marks", 0),
            "difficulty": question_data.get("difficulty"),
            "guidelines": question_data.get("guidelines"),
            "createdAt": question_data.get("createdAt"),
            "negativeMark": question_data.get("negativeMark", 0)
        }

        # Add type-specific fields
        if question_type == "MCQ":
            base_data.update({
                "options": question_data.get("options", []),
                "answer": question_data.get("answer", [])
            })
        elif question_type == "TRUE_FALSE":
            base_data.update({
                "options": question_data.get("options", []),
                "answer": question_data.get("answer", [])
            })
        elif question_type in ["DESCRIPTIVE", "FILL_IN_BLANK"]:
            base_data.update({
                "expectedAnswer": question_data.get("expectedAnswer", "")
            })
        elif question_type == "CODING":
            base_data.update({
                "driverCode": question_data.get("driverCode", ""),
                "testcases": question_data.get("testcases", []),
                "language": question_data.get("language", "python")
            })

        return base_data
    
    def _validate_answer_format(self, question_type: str, answer: Any) -> bool:
        """Validate the answer format based on question type"""
        if question_type == "MCQ":
            return isinstance(answer, list) and all(isinstance(opt, str) for opt in answer)
        elif question_type == "TRUE_FALSE":
            return isinstance(answer, list) and len(answer) == 1 and isinstance(answer[0], str)
        elif question_type in ["DESCRIPTIVE", "FILL_IN_BLANK"]:
            return isinstance(answer, str)
        elif question_type == "CODING":
            return isinstance(answer, dict) and "driverCode" in answer
        return False
    
    def _format_student_answer(self, answer: Any, question_type: str) -> Any:
        """Format student answer based on question type for consistent storage"""
        if question_type in ["MCQ", "TRUE_FALSE"]:
            if isinstance(answer, str):
                return [answer]
            elif isinstance(answer, list):
                return answer
            return []
        elif question_type in ["DESCRIPTIVE", "FILL_IN_BLANK"]:
            if isinstance(answer, list) and len(answer) > 0:
                return answer[0]
            return str(answer) if answer else ""
        return answer

    def log_question_evaluation(
        self,
        question_id: str,
        question_data: Dict[str, Any],
        student_id: str,
        response_data: Dict[str, Any],
        evaluation_result: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log the evaluation of a single question with type-specific handling"""
        question_type = question_data.get("type", "").upper()
        
        if question_id not in self.evaluation_data:
            self.evaluation_data[question_id] = {
                "question": self._get_question_data(question_data),
                "responses": {},
                "statistics": {
                    "attempted": 0,
                    "average_score": 0,
                    "max_score": 0,
                    "passing_count": 0  # score >= 60% of max marks
                }
            }
        
        # Format student answer consistently
        student_answer = self._format_student_answer(
            response_data.get("student_answer"),
            question_type
        )
        
        # Prepare response data
        score = evaluation_result.get("score", 0)
        response_entry = {
            "studentAnswer": student_answer,
            "score": score,
            "remarks": evaluation_result.get("remarks"),
            "breakdown": evaluation_result.get("breakdown"),
            "negative_score": evaluation_result.get("negative_score", 0),
            "evaluatedAt": datetime.now().isoformat()
        }

        # Add type-specific evaluation details
        if question_type == "CODING":
            response_entry.update({
                "testCasesPassed": evaluation_result.get("testCasesPassed", []),
                "executionError": evaluation_result.get("executionError"),
                "memoryUsage": evaluation_result.get("memoryUsage"),
                "executionTime": evaluation_result.get("executionTime")
            })
        elif question_type == "DESCRIPTIVE":
            response_entry.update({
                "rubric": evaluation_result.get("rubric"),
                "breakdown": evaluation_result.get("breakdown"),
                "keyPointsMatched": evaluation_result.get("keyPointsMatched", [])
            })
        elif question_type in ["MCQ", "TRUE_FALSE"]:
            response_entry.update({
                "isCorrect": score == question_data.get("mark", 0),
                "selectedOptions": student_answer
            })
        
        # Add metadata
        response_entry["metadata"] = {
            "evaluationType": question_type,
            "timestamp": datetime.now().isoformat(),
            **(metadata or {})
        }
        
        # Update response in evaluation data
        self.evaluation_data[question_id]["responses"][student_id] = response_entry
        
        # Update statistics
        stats = self.evaluation_data[question_id]["statistics"]
        responses = self.evaluation_data[question_id]["responses"]
        stats["attempted"] = len(responses)
        if responses:
            scores = [r["score"] for r in responses.values()]
            stats["average_score"] = sum(scores) / len(scores)
            stats["max_score"] = max(scores)
            max_marks = question_data.get("mark", 0)
            stats["passing_count"] = sum(1 for s in scores if s >= 0.6 * max_marks)
        
        # Save after each update
        self._save_log()
    
    def get_question_evaluations(self, question_id: str) -> Dict:
        """Get all evaluations for a specific question"""
        return self.evaluation_data.get(question_id, {})
    
    def get_student_evaluations(self, student_id: str) -> Dict:
        """Get all question evaluations for a specific student"""
        student_evals = {}
        for q_id, q_data in self.evaluation_data.items():
            if student_id in q_data.get("responses", {}):
                student_evals[q_id] = {
                    "question": q_data["question"],
                    "response": q_data["responses"][student_id]
                }
        return student_evals
    
    def get_student_summary(self, student_id: str) -> Dict:
        """Get a summary of a student's performance across all questions"""
        evals = self.get_student_evaluations(student_id)
        total_score = 0
        total_possible = 0
        question_type_scores = {}
        
        for q_id, data in evals.items():
            score = data["response"]["score"]
            question_type = data["question"]["type"]
            total_score += score
            total_possible += data["question"]["mark"]
            
            if question_type not in question_type_scores:
                question_type_scores[question_type] = {"score": 0, "possible": 0}
            question_type_scores[question_type]["score"] += score
            question_type_scores[question_type]["possible"] += data["question"]["mark"]
        
        return {
            "studentId": student_id,
            "totalScore": total_score,
            "totalPossible": total_possible,
            "percentage": (total_score / total_possible * 100) if total_possible > 0 else 0,
            "questionTypeBreakdown": question_type_scores,
            "evaluatedAt": datetime.now().isoformat()
        }
    
    def get_question_statistics(self, question_id: str) -> Dict:
        """Get statistical analysis for a specific question"""
        if question_id not in self.evaluation_data:
            return {}
            
        question_data = self.evaluation_data[question_id]
        responses = question_data["responses"]
        question_type = question_data["question"]["type"]
        max_marks = question_data["question"]["mark"]
        
        stats = {
            "basic": question_data["statistics"],
            "scoreDistribution": {
                "excellent": 0,  # 80-100%
                "good": 0,      # 60-79%
                "average": 0,   # 40-59%
                "poor": 0       # 0-39%
            },
            "commonErrors": []
        }
        
        if not responses:
            return stats
            
        # Calculate score distribution
        for response in responses.values():
            score_percentage = (response["score"] / max_marks) * 100
            if score_percentage >= 80:
                stats["scoreDistribution"]["excellent"] += 1
            elif score_percentage >= 60:
                stats["scoreDistribution"]["good"] += 1
            elif score_percentage >= 40:
                stats["scoreDistribution"]["average"] += 1
            else:
                stats["scoreDistribution"]["poor"] += 1
        
        # Add type-specific statistics
        if question_type == "MCQ":
            stats["optionDistribution"] = {}
            for response in responses.values():
                for option in response.get("selectedOptions", []):
                    stats["optionDistribution"][option] = stats["optionDistribution"].get(option, 0) + 1
        elif question_type == "CODING":
            stats["averageExecutionTime"] = sum(
                response.get("executionTime", 0) for response in responses.values()
            ) / len(responses)
            stats["commonErrors"] = self._analyze_common_errors(responses)
        
        return stats
    
    def _analyze_common_errors(self, responses: Dict[str, Any]) -> list:
        """Analyze common errors in responses"""
        error_counts = {}
        for response in responses.values():
            error = response.get("executionError") or response.get("remarks")
            if error:
                error_counts[error] = error_counts.get(error, 0) + 1
        
        # Return top 5 most common errors
        return sorted(
            [{"error": k, "count": v} for k, v in error_counts.items()],
            key=lambda x: x["count"],
            reverse=True
        )[:5]
    
    def _save_log(self) -> None:
        """Save the evaluation data to file"""
        with open(self.log_file, 'w') as f:
            json.dump(self.evaluation_data, f, indent=2)