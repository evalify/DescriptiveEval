"""This module contains simple utility functions"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.logger import logger


class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()  # Convert to ISO format
        return super().default(obj)


# Create a function that will remove all html tags in a given string
def remove_html_tags(data):
    p = re.compile(
        r"<.*?>"
    )  # TODO: Escape html tags when question itself needs explicit html tags like a UI quiz
    return p.sub("", data)


def save_quiz_data(data: Any, quiz_id: str, file_type: str) -> None:
    """
    Save quiz related data to a JSON file in a quiz-specific directory.

    Args:
        data: The data to save (must be JSON serializable)
        quiz_id: The ID of the quiz
        file_type: Type of data ('questions', 'responses', 'responses_evaluated', 'report')
    """
    try:
        # Create quiz directory if it doesn't exist
        quiz_dir = Path("data/json") / quiz_id
        quiz_dir.mkdir(parents=True, exist_ok=True)

        # Determine filename based on type
        filename = f"{file_type}.json"
        file_path = quiz_dir / filename

        with open(file_path, "w") as f:
            json.dump(data, f, indent=4, cls=DateTimeEncoder)
        logger.debug(f"Saved {file_type} data for quiz {quiz_id}")

    except IOError as e:
        logger.error(f"Failed to save {file_type} data for quiz {quiz_id}: {str(e)}")
    except Exception as e:
        logger.error(
            f"Unexpected error saving {file_type} data for quiz {quiz_id}: {str(e)}",
            exc_info=True,
        )


if __name__ == "__main__":
    # Sample data
    my_data = {
        "_id": "678f1e9ddf031e96652e5c1e",
        "type": "MCQ",
        "difficulty": "MEDIUM",
        "mark": 1,
        "question": "<p>Four different mathematics books, six different physics books and two different chemistry books are to be arranged on a shelf. How many different arrangements are possible if only the mathematics books must stand together?&nbsp;&nbsp;</p><p></p>",
        "created_at": datetime.now(),
    }

    # Convert data to JSON with custom DateTimeEncoder
    json_data = json.dumps(
        my_data, cls=DateTimeEncoder, indent=4
    )  # Testing the DateTimeEncoder
    print(json_data)

    # Remove HTML tags from description
    cleaned_description = remove_html_tags(
        my_data["question"]
    )  # Testing the remove_html_tags function
    print(cleaned_description)
