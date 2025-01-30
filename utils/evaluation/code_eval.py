"""This module contains utility functions for evaluating coding questions"""

import json
import os
import re
from typing import Tuple

import requests
from dotenv import load_dotenv

load_dotenv()

JUDGE_URL = os.getenv("JUDGE_API")


async def evaluate_coding_question(student_response: str, driver_code: str, test_cases_count: int = -1) -> Tuple[
    int, int]:
    """
    Evaluate a single student response against test cases
    Returns the number of test cases passed and the total number of test cases

    :param student_response: Student's response aka boilerplate code
    :param driver_code: Driver code to run the student's code
    :param test_cases_count: Number of test cases that are in the driver code for validation (optional)
    """
    if not student_response:
        print(f"⚠️ No response submitted")
        return 0

    code_index = student_response.rfind('% Driver Code')
    cleaned_code = cleanCode(student_response[:code_index] if code_index != -1 else student_response)

    try:
        code_output = get_code_result(cleaned_code, driver_code)
        if code_output.get('stdout'):
            passed_cases, total_cases = count_test_cases(code_output['stdout'])

            if test_cases_count != -1 and total_cases != test_cases_count:
                print(f"❌ Expected {test_cases_count} test cases but got {total_cases}")
                return -1, -1

            if passed_cases == total_cases and total_cases > 0:
                print(f"✓ All test cases passed")
            return passed_cases, total_cases
        print(f"❌ No output received")
    except requests.exceptions.ReadTimeout:
        print(f'❌ Unable to evaluate code - Timeout')
    except Exception as e:
        print(f'❌ Error evaluating code: {str(e)}')

    return 0, -1


def cleanCode(code: str) -> str:
    """
    This function cleans the code by adding semicolons and commenting out print statements
    :param code: Raw code
    :return: Cleaned code
    """
    # Regex pattern to match lines without a semicolon at the end
    semicolon_pattern = r'([^\s;]+)(\s*)(%.*)?$'

    # Regex pattern to match lines with printing functions (e.g., disp, fprintf)
    print_pattern = r'^\s*(disp|fprintf)\(.*\)\s*;?'

    # Function to add semicolon to the matched lines
    def add_semicolon(match):
        code_line = match.group(1)  # The actual code
        whitespace = match.group(2) or ''  # Any trailing whitespace
        comment = match.group(3) or ''  # Any trailing comment
        return f'{code_line};{whitespace}{comment}'

    # Function to comment out lines that will lead to printing
    def comment_out_prints(match):
        return f'% {match.group(0)}'  # Comment out the entire line

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
    test_cases = code_output.split('\n')
    successful = test_cases.count('Test case successful!')
    failed = test_cases.count('Test case failed!')
    return successful, successful + failed


def get_code_result(response: str, driver_code: str = None, language_id: int = 66) -> dict:
    """
    This function takes the response code and driver code and returns the output of the code
    :param response: Student's code
    :param driver_code: Driver code to run the student's code
    :param language_id: Language ID for the code, Default is Octave (66)
    :return: Output of the code
    """
    if driver_code is not None:
        code = f"_temp = 1;\n{response}\n{driver_code}"
    else:
        code = response

    headers = {
        "Content-Type": "application/json"
    }
    data = {
        "source_code": code,
        "language_id": language_id  # For Octave
    }
    if not JUDGE_URL:
        raise ValueError("JUDGE_API is not set in the environment variables")
    url = f"{JUDGE_URL}/submissions/?base64_encoded=false&wait=true"
    response = requests.post(url, data=json.dumps(data), headers=headers)
    if response.status_code == 201:
        return response.json()

    return f"Error: {response.status_code}"
