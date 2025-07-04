from langchain.output_parsers import ResponseSchema, StructuredOutputParser
from langchain_core.prompts import PromptTemplate
from .templates import (
    evaluation_template,
    guidelines_template,
    qa_enhancement_template,
    fill_in_the_blank_template,
)
from app.core.logger import logger
from app.config.enums import EvaluationStatus, LLMProvider
from app.api.provider.service import get_llm
from app.config.constants import MAX_RETRIES


async def score(
    llm,
    student_ans: str,
    expected_ans: str,
    total_score: float,
    question: str = None,
    guidelines: str = None,
    errors=None,
) -> dict:
    """
    Evaluate a student's answer based on the expected answer and guidelines.

    :param llm: The LLM instance to use for scoring
    :param student_ans: The student's answer to evaluate
    :param expected_ans: The expected answer for comparison
    :param total_score: The total score to evaluate against
    :param question: The question (optional)
    :param guidelines: The evaluation guidelines and criteria (optional)
    :param errors: Any errors encountered during evaluation (optional)
    """
    if not expected_ans or expected_ans.strip() == "" or total_score <= 0:
        logger.error(
            f"Invalid input parameters: expected_ans='{expected_ans}', total_score='{total_score}'"
        )
        return {
            "rubric": "Error: Invalid input parameters",
            "breakdown": "Error: Invalid input parameters",
            "score": 0.0,
            "reason": f"Error: Invalid input parameters: expected_ans='{expected_ans}', total_score='{total_score}'",
            "status": EvaluationStatus.INVALID_INPUT,
        }

    if not student_ans or student_ans.strip() == "":
        logger.warning("Student answer is empty or missing")
        return {
            "rubric": "Error: Student answer is empty or missing",
            "breakdown": "Error: Student answer is empty or missing",
            "score": 0.0,
            "reason": "Error: Student answer is empty or missing",
            "status": EvaluationStatus.EMPTY_ANSWER,
        }

    # Update response schemas to include 'rubric' and 'breakdown'
    response_schemas = [
        ResponseSchema(
            name="rubric",
            description="The evaluation rubric as a markdown formatted string - you are just stating the general evaluation criteria",
        ),
        ResponseSchema(
            name="breakdown",
            description="Detailed breakdown of the allocated marks as a markdown formatted string, along with the reasoning behind each criterion's score",
        ),
        ResponseSchema(
            name="score", description="The assigned score as a floating point number"
        ),
        ResponseSchema(
            name="reason",
            description="A Detailed Reason for the assigned score",
        ),
    ]

    output_parser = StructuredOutputParser.from_response_schemas(response_schemas)
    format_instructions = output_parser.get_format_instructions()
    question_context = " to the question" if question else ""
    question_section = f"\nQuestion:\n{question}\n" if question else "\n"
    guidelines_section = (
        f"\nQuestion-specific Guidelines:\n{guidelines}\n" if guidelines else "\n"
    )

    prompt_template = PromptTemplate(
        input_variables=["student_ans", "expected_ans", "total_score", "errors"],
        partial_variables={
            "format_instructions": format_instructions,
            "question_context": question_context,
            "question_section": question_section,
            "guidelines_section": guidelines_section,
        },
        template=evaluation_template,
    )

    _input = prompt_template.format(
        student_ans=student_ans,
        expected_ans=expected_ans,
        total_score=total_score,
        errors=errors,
    )

    response = parsed_response = None
    try:
        for i in range(MAX_RETRIES + 1):
            response = await llm.ainvoke(_input)
            if hasattr(response, "content"):
                response = response.content
            elif not isinstance(response, str):
                response = str(response)

            try:
                parsed_response = output_parser.parse(response)
            except Exception as e:
                logger.debug("Detailed Stack Trace for below error", exc_info=True)
                logger.warning(
                    f"Retrying {i}/{MAX_RETRIES} because Unable to parse response error {str(e)}"
                )
                parsed_response = {
                    "rubric": "Error: Failed to parse LLM response",
                    "breakdown": "Error: Failed to parse LLM response",
                    "score": 0.0,
                    "reason": f"Error: Failed to parse LLM response: {str(e)}",
                    "status": EvaluationStatus.PARSE_ERROR,
                }
            else:
                if i > 0:
                    logger.info(f"Successfully scored response after {i} attempt(s)")
                break

        assert parsed_response is not None, "Error: Failed to get/parse response"
        assert float(parsed_response.get("score", 0.0)) <= total_score, (
            f"Error: Score exceeds total score Given {total_score=} but Got {parsed_response.get('score', 0.0)}"
        )

        # Add success status if not present
        if "status" not in parsed_response:
            parsed_response["status"] = EvaluationStatus.SUCCESS

        return {
            "rubric": str(parsed_response.get("rubric", "No rubric available")),
            "breakdown": str(
                parsed_response.get("breakdown", "No breakdown available")
            ),
            "score": float(parsed_response.get("score", 0.0)),
            "reason": str(parsed_response.get("reason", "No reason provided")),
            "status": parsed_response.get("status", EvaluationStatus.LLM_ERROR),
        }
    except Exception as e:
        logger.warning(f"Error processing response: {str(e)}")
        with open("logs/score_error.log", "a") as f:
            f.write(f"Error: {str(e)}\n")
            f.write(f"Response: {response}\n\n-----------------\n\n")
        return {
            "rubric": "Error: Could not generate rubric",
            "breakdown": "Error: Could not generate breakdown",
            "score": 0.0,
            "reason": f"Error: Error processing response: {str(e)}",
            "status": EvaluationStatus.LLM_ERROR,
        }


async def generate_guidelines(
    llm, question: str, expected_ans: str, total_score: int = 5, errors=None
) -> dict:
    """
    Generate evaluation guidelines and criteria for a given question and expected answer.

    :param llm: The LLM instance to use for generating guidelines
    :param question: The question to evaluate
    :param expected_ans: The expected answer for comparison
    :param total_score: The total score to evaluate against
    :param errors: Any errors encountered during evaluation (optional)
    """
    if not question or not expected_ans:
        logger.error(
            "Provide a question and expected answer to generate evaluation rubric/guidelines"
        )
        return {
            "status": 403,
            "guidelines": "Error: Provide a question and expected answer to generate evaluation rubric/guidelines",
            "error": "Missing required parameters",
        }

    # Define response schema for guidelines
    guidelines_schema = [
        ResponseSchema(name="guidelines", description="The evaluation guidelines")
    ]
    guidelines_parser = StructuredOutputParser.from_response_schemas(guidelines_schema)
    format_instructions = guidelines_parser.get_format_instructions()

    prompt_template = PromptTemplate(
        input_variables=["question", "expected_ans", "score", "errors"],
        partial_variables={"format_instructions": format_instructions},
        template=guidelines_template,
    )

    response = parsed_response = None
    try:
        for i in range(MAX_RETRIES + 1):
            _input = prompt_template.format(
                question=question,
                expected_ans=expected_ans,
                score=total_score,
                errors=errors,
            )
            response = await llm.ainvoke(_input)
            if hasattr(response, "content"):
                response = response.content
            elif not isinstance(response, str):
                response = str(response)
            try:
                parsed_response = guidelines_parser.parse(response)
                assert parsed_response is not None, (
                    "Error: Failed to get/parse response"
                )
            except Exception as e:
                logger.debug("Detailed Stack Trace for below error", exc_info=True)
                logger.warning(
                    f"Retrying {i}/{MAX_RETRIES} because Unable to parse response error {str(e)}"
                )
                errors.append(
                    f"Unable to parse response error {str(e)}. Response: {response}"
                )
            else:
                if i > 0:
                    logger.info(f"Successfully scored response after {i} attempt(s)")
                break
            finally:
                if i == MAX_RETRIES:
                    logger.warning(
                        f"Failed to parse response after {MAX_RETRIES} attempts. Response: {response}. Returning Json without parsing"
                    )
                    return {
                        "status": 200,
                        "guidelines": str(
                            response
                        ),  # Return the raw response if parsing fails
                    }
        assert parsed_response is not None, "Error: Failed to get/parse response"
        return {
            "status": 200,
            "guidelines": "The Following is in json, just use the guidelines provided"
            + str(parsed_response.get("guidelines", "No guidelines available")),
        }
    except Exception as e:
        logger.error(f"Error processing response: {str(e)}. {response=}", exc_info=True)
        return {
            "status": 403,
            "guidelines": "Error: Error processing response",
            "error": str(e),
            "prompt": prompt_template.format(
                question=question,
                expected_ans=expected_ans,
                score=total_score,
                errors=errors,
            ),
        }


async def enhance_question_and_answer(
    llm, question: str, expected_ans: str, errors: list = None
) -> dict:
    """
    Enhance the question and expected answer to be clear, concise, and direct.

    :param llm: The LLM instance to use for enhancing the content
    :param question: The question to enhance
    :param expected_ans: The expected answer to enhance
    :param errors: Any errors encountered during enhancement (optional)
    """
    if errors is None:
        errors = []

    if not question or not expected_ans:
        logger.error("Provide a question and expected answer to enhance the content")
        return {
            "status": 403,
            "enhanced_question": "Provide a question and expected answer to enhance the content",
            "enhanced_expected_ans": "Provide a question and expected answer to enhance the content",
            "error": "Missing required parameters",
        }

    # Define response schema for enhanced content
    enhanced_content_schema = [
        ResponseSchema(name="enhanced_question", description="The enhanced question"),
        ResponseSchema(
            name="enhanced_expected_ans", description="The enhanced expected answer"
        ),
    ]
    enhanced_content_parser = StructuredOutputParser.from_response_schemas(
        enhanced_content_schema
    )
    format_instructions = enhanced_content_parser.get_format_instructions()

    prompt_template = PromptTemplate(
        input_variables=["question", "expected_ans", "errors"],
        partial_variables={"format_instructions": format_instructions},
        template=qa_enhancement_template,
    )

    _input = prompt_template.format(
        question=question, expected_ans=expected_ans, errors=errors
    )

    try:
        response = await llm.ainvoke(_input)
        if hasattr(response, "content"):
            response = response.content
        elif not isinstance(response, str):
            response = str(response)

        parsed_response = enhanced_content_parser.parse(response)
        return {
            "status": 200,
            "enhanced_question": str(
                parsed_response.get(
                    "enhanced_question", "No enhanced question available"
                )
            ),
            "enhanced_expected_ans": str(
                parsed_response.get(
                    "enhanced_expected_ans", "No enhanced expected answer available"
                )
            ),
        }
    except Exception as e:
        logger.error(f"Error processing response: {str(e)}", exc_info=True)
        return {
            "status": 403,
            "enhanced_question": "Error processing response",
            "enhanced_expected_ans": "Error processing response",
            "error": str(e),
        }


async def score_fill_in_blank(
    llm, student_ans: str, expected_ans: str, total_score: float, question: str
) -> dict:
    """
    Evaluate fill in the blank questions based on the expected answer and guidelines.

    :param llm: The LLM instance to use for scoring
    :param student_ans: The student's answer to evaluate
    :param expected_ans: The expected answer for comparison
    :param total_score: The total score to evaluate for
    :param question: The question
    """
    if not expected_ans or expected_ans.strip() == "":
        logger.warning("Expected answer is empty or missing")
        return {
            "score": 0.0,
            "reason": "Error: Expected answer is empty or missing",
            "status": EvaluationStatus.INVALID_INPUT,
        }

    if not student_ans or student_ans.strip() == "":
        logger.warning("Student answer is empty or missing")
        return {
            "score": 0.0,
            "reason": "Error: Student answer is empty or missing",
            "status": EvaluationStatus.EMPTY_ANSWER,
        }

    # Update response schemas to include 'rubric' and 'breakdown'
    response_schemas = [
        ResponseSchema(
            name="reason",
            description="A short and concise reason for the assigned score",
        ),
        ResponseSchema(
            name="score", description="The assigned score as a floating point number"
        ),
    ]

    output_parser = StructuredOutputParser.from_response_schemas(response_schemas)
    format_instructions = output_parser.get_format_instructions()
    question_section = f"\nQuestion:\n{question}\n" if question else "\n"

    prompt_template = PromptTemplate(
        input_variables=["student_ans", "expected_ans", "total_score"],
        partial_variables={
            "format_instructions": format_instructions,
            "question_section": question_section,
        },
        template=fill_in_the_blank_template,
    )

    _input = prompt_template.format(
        student_ans=student_ans, expected_ans=expected_ans, total_score=total_score
    )

    response = parsed_response = None
    try:
        for i in range(MAX_RETRIES + 1):
            response = await llm.ainvoke(_input)
            if hasattr(response, "content"):
                response = response.content
            elif not isinstance(response, str):
                response = str(response)
            try:
                parsed_response = output_parser.parse(response)
            except Exception as e:
                logger.debug("Detailed Stack Trace for below error", exc_info=True)
                logger.warning(
                    f"Retrying {i}/{MAX_RETRIES} because Unable to parse response error {str(e)}"
                )
            else:
                if i > 0:
                    logger.info(f"Successfully scored response after {i} attempt(s)")
                break
        assert parsed_response is not None, "Error: Failed to get/parse response"
        assert float(parsed_response.get("score", 0.0)) <= total_score, (
            f"Error: Score exceeds total score Given {total_score=} but Got {parsed_response.get('score', 0.0)}"
        )

        return {
            "score": float(parsed_response.get("score", 0.0)),
            "reason": str(parsed_response.get("reason", "No reason provided")),
            "status": EvaluationStatus.SUCCESS,
        }
    except Exception as e:
        logger.warning(f"Error processing response: {str(e)}")
        return {
            "score": 0.0,
            "reason": f"Error: Error processing response: {str(e)}",
            "status": EvaluationStatus.LLM_ERROR,
        }


if __name__ == "__main__":
    import asyncio
    import time

    my_llm = get_llm(provider=LLMProvider.OLLAMA, model_name="deepseek-r1:70b")
    # Test fill in the blank scoring
    my_question = "The Capital of France is ________."
    my_expected_ans = "Paris"
    my_student_ans = "Pariess"
    my_total_score = 1
    start = time.time()
    result = asyncio.run(
        score_fill_in_blank(
            my_llm, my_student_ans, my_expected_ans, my_total_score, my_question
        )
    )
    print(f"Fill in the blank scoring took: {time.time() - start} seconds")
    print(result)
