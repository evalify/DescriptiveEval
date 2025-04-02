"""This module contains utility functions for evaluating coding questions"""

import json
from app.config.constants import JUDGE_URL, JUDGE_LANGUAGE_MAP
import re
from typing import Tuple

import requests
from dotenv import load_dotenv
from app.core.logger import logger
from app.core.exceptions import InvalidQuestionError

load_dotenv()


async def evaluate_coding_question(
    student_response: str,
    language: str,
    driver_code: str,
    test_cases_count: int = -1,
) -> Tuple[int, int, str]:
    """
    Evaluate a single student response against test cases
    Returns the number of test cases passed and the total number of test cases and the code output

    :param student_response: Student's response aka boilerplate code
    :param driver_code: Driver code to run the student's code
    :param test_cases_count: Number of test cases that are in the driver code for validation (optional)
    """
    if test_cases_count == 0:
        # Infer test cases count from the driver code
        test_cases_count = driver_code.count("successful!")
        if test_cases_count == 0:
            raise InvalidQuestionError("No Test Cases are present in driver code")

    if not student_response:
        logger.warning("No response submitted")
        return 0, test_cases_count, ""

    language_id = JUDGE_LANGUAGE_MAP.get(language)
    if language_id is None:
        logger.error(f"Unsupported language: {language}")
        return 0, test_cases_count, f"Unsupported language {language}"

    cleaned_code = cleanCode(student_response, language_id)

    code_output = {}
    try:
        code_output = get_code_result(
            cleaned_code, driver_code, language_id=language_id
        )
        if code_output.get("stdout"):
            passed_cases, total_cases = count_test_cases(code_output["stdout"])

            if total_cases == 0:
                logger.warning(
                    "No test cases detected, probably an input function or inf loop"
                )
                return (
                    0,
                    test_cases_count,
                    code_output["stdout"] + (code_output.get("stderr") or ""),
                )

            if test_cases_count != -1 and total_cases != test_cases_count:
                logger.warning(
                    f"Expected {test_cases_count} test cases but got {total_cases}"
                )
                return (
                    0,
                    test_cases_count,
                    code_output["stdout"] + (code_output.get("stderr") or ""),
                )

            if passed_cases == total_cases and total_cases > 0:
                logger.info("All test cases passed")
            return passed_cases, total_cases, code_output["stdout"]
        logger.warning("No output received")
    except requests.exceptions.ReadTimeout:
        logger.error("Unable to evaluate code - Timeout")
    except Exception as e:
        logger.error(f"Error evaluating code: {str(e)}")

    return (
        0,
        test_cases_count,
        (code_output.get("stdout") or "") + (code_output.get("stderr") or ""),
    )


def cleanCode(code: str, language_id) -> str:
    if language_id == JUDGE_LANGUAGE_MAP["octave"]:
        return cleanCode_octave(code)
    elif language_id == JUDGE_LANGUAGE_MAP["python"]:
        return cleanCode_python(code)
    elif language_id == JUDGE_LANGUAGE_MAP["java"]:
        return cleanCode_java(code)
    else:
        raise ValueError(
            f"Unsupported language ID {language_id}. Supported IDs are {JUDGE_LANGUAGE_MAP}"
        )


def cleanCode_java(code: str) -> str:
    """
    This function cleans the code by removing all print statements
    :param code: Raw code
    :return: Cleaned code
    """
    # Regex pattern to match print statements
    print_pattern = r"^\s*System\.out\.(?:print(?:ln)?|printf)\s*\(.*?\)\s*;?\s*$"

    # Function to comment out lines that will lead to printing
    def comment_out_prints(match):
        return f"// {match.group(0)}"  # Comment out the entire line

    # Comment out all printing lines
    code = re.sub(print_pattern, comment_out_prints, code, flags=re.MULTILINE)

    return code


def cleanCode_python(code: str) -> str:
    """
    This function cleans the code by removing all print statements
    :param code: Raw code
    :return: Cleaned code
    """
    # Regex pattern to match print statements
    print_pattern = r"^\s*print\(.*\)\s*;?"

    # Function to comment out lines that will lead to printing
    def comment_out_prints(match):
        return f"# {match.group(0)}"  # Comment out the entire line

    # Comment out all printing lines
    code = re.sub(print_pattern, comment_out_prints, code, flags=re.MULTILINE)

    return code


def cleanCode_octave(code: str) -> str:
    """
    This function cleans the code by adding semicolons and commenting out print statements
    :param code: Raw code
    :return: Cleaned code
    """
    # Regex pattern to match lines without a semicolon at the end
    semicolon_pattern = r"([^\s;]+)(\s*)(%.*)?$"

    # Regex pattern to match lines with printing functions (e.g., disp, fprintf)
    print_pattern = r"^\s*(disp|fprintf)\(.*\)\s*;?"

    # Function to add semicolon to the matched lines
    def add_semicolon(match):
        code_line = match.group(1)  # The actual code
        whitespace = match.group(2) or ""  # Any trailing whitespace
        comment = match.group(3) or ""  # Any trailing comment
        return f"{code_line};{whitespace}{comment}"

    # Function to comment out lines that will lead to printing
    def comment_out_prints(match):
        return f"% {match.group(0)}"  # Comment out the entire line

    # First, comment out all printing lines
    code = re.sub(print_pattern, comment_out_prints, code, flags=re.MULTILINE)

    # Then, add semicolons where necessary
    code = re.sub(semicolon_pattern, add_semicolon, code, flags=re.MULTILINE)

    return code


def count_test_cases(code_output: str) -> tuple[int, int]:
    """
    Count the number of successful test cases
    The Code outputs
    Test case successful!
    Test case failed!
    Test case successful!

    Returns the number of successful test cases
    ...
    :param code_output:
    :return: successful, total test cases
    """
    test_cases = code_output.split("\n")
    successful = test_cases.count("Test case successful!")
    failed = test_cases.count("Test case failed!")
    return successful, successful + failed


def get_code_result(
    response: str,
    driver_code: str = None,
    language_id: int = JUDGE_LANGUAGE_MAP["octave"],
) -> dict:
    """
    This function takes the response code and driver code and returns the output of the code
    :param response: Student's code
    :param driver_code: Driver code to run the student's code
    :param language_id: Language ID for the code, Default is Octave (66)
    :return: Output of the code
    """
    code = response
    if language_id == JUDGE_LANGUAGE_MAP["octave"]:
        code = f"_temp = 1;\n{code}"
    if driver_code is not None:
        code = f"{code}\n{driver_code}"

    headers = {"Content-Type": "application/json"}
    data = {
        "source_code": code,
        "language_id": language_id,
    }
    if not JUDGE_URL:
        raise ValueError("JUDGE_API is not set in the environment variables")
    url = f"{JUDGE_URL}/submissions/?base64_encoded=false&wait=true"
    response = requests.post(url, data=json.dumps(data), headers=headers)
    if response.status_code == 201:
        return response.json()

    return f"Error: {response.status_code}"
