import os
from enum import Enum

from dotenv import load_dotenv
from langchain.output_parsers import ResponseSchema, StructuredOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_groq import ChatGroq
from langchain_ollama import OllamaLLM

load_dotenv()

from utils.evaluation.templates import evaluation_template, guidelines_template, qa_enhancement_template, fill_in_the_blank_template
from utils.logger import logger
from utils.errors import InvalidProviderError, InvalidInputError, EmptyAnswerError

class LLMProvider(Enum):
    OLLAMA = "ollama"
    GROQ = "groq"


def get_llm(provider: LLMProvider = LLMProvider.GROQ, api_key=None, model_name=None):
    """
    Get an LLM instance with the specified provider

    :param provider: The LLM provider to use
    :param api_key: The API key for the provider (optional)
    :param model_name: The model name for the provider (optional)
    """
    if provider == LLMProvider.OLLAMA:
        return OllamaLLM(model=model_name if model_name else "llama3.3",
                         base_url=os.getenv("OLLAMA_HOST", "http://localhost:11434"))
    elif provider == LLMProvider.GROQ:
        return ChatGroq(
            api_key=api_key if api_key else os.getenv("GROQ_API_KEY"),
            model_name=model_name if model_name else "llama-3.3-70b-specdec",
            temperature=0.2,
        )
    else:
        raise InvalidProviderError(provider)


async def score(llm, student_ans:str, expected_ans:str, total_score:float, question:str=None, guidelines:str=None, errors=None) -> dict:
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
        logger.error(f"Invalid input parameters: expected_ans='{expected_ans}', total_score='{total_score}'")
        raise InvalidInputError("expected_ans or total_score", f"expected_ans='{expected_ans}', total_score='{total_score}'")

    if not student_ans or student_ans.strip() == "":
        logger.error("Student answer is empty or missing")
        raise EmptyAnswerError()

    # Update response schemas to include 'rubric' and 'breakdown'
    response_schemas = [
        ResponseSchema(name="rubric", description="The evaluation rubric as a markdown formatted string"),
        ResponseSchema(name="score", description="The assigned score as a floating point number"),
        ResponseSchema(name="reason", description="A short and concise reason for the assigned score"),
        ResponseSchema(name="breakdown",
                       description="Detailed breakdown of the allocated marks as a markdown formatted string"),
    ]

    output_parser = StructuredOutputParser.from_response_schemas(response_schemas)
    format_instructions = output_parser.get_format_instructions()
    question_context = " to the question" if question else ""
    question_section = f"\nQuestion:\n{question}\n" if question else "\n"
    guidelines_section = f"\nQuestion-specific Guidelines:\n{guidelines}\n" if guidelines else "\n"

    prompt_template = PromptTemplate(
        input_variables=['student_ans', 'expected_ans', 'total_score', 'errors'],
        partial_variables={
            "format_instructions": format_instructions,
            "question_context": question_context,
            "question_section": question_section,
            "guidelines_section": guidelines_section
        },
        template=evaluation_template
    )

    _input = prompt_template.format(
        student_ans=student_ans,
        expected_ans=expected_ans,
        total_score=total_score,
        errors=errors
    )

    response = None
    try:
        response = await llm.ainvoke(_input)
        if hasattr(response, 'content'):
            response = response.content
        elif not isinstance(response, str):
            response = str(response)

        parsed_response = output_parser.parse(response)
        assert float(parsed_response.get("score", 0.0)) <= total_score, "Error: Score exceeds total score"
        return {
            "rubric": str(parsed_response.get("rubric", "No rubric available")),
            "breakdown": str(parsed_response.get("breakdown", "No breakdown available")),
            "score": float(parsed_response.get("score", 0.0)),
            "reason": str(parsed_response.get("reason", "No reason provided"))
        }
    except Exception as e:
        logger.error(f"Error processing response: {str(e)}", exc_info=True)
        with open("logs/score_error.log", "a") as f:
            f.write(f"Error: {str(e)}\n")
            f.write(f"Response: {response}\n\n-----------------\n\n")
        raise


async def generate_guidelines(llm, question: str, expected_ans: str, total_score: int = 5, errors = None) -> dict:
    """
    Generate evaluation guidelines and criteria for a given question and expected answer.

    :param llm: The LLM instance to use for generating guidelines
    :param question: The question to evaluate
    :param expected_ans: The expected answer for comparison
    :param total_score: The total score to evaluate against
    :param errors: Any errors encountered during evaluation (optional)
    """
    if not question or not expected_ans:
        logger.error("Provide a question and expected answer to generate evaluation rubric/guidelines")
        raise InvalidInputError("question or expected_ans", f"question='{question}', expected_ans='{expected_ans}'")

    # Define response schema for guidelines
    guidelines_schema = [
        ResponseSchema(name="guidelines", description="The evaluation guidelines")
    ]
    guidelines_parser = StructuredOutputParser.from_response_schemas(guidelines_schema)
    format_instructions = guidelines_parser.get_format_instructions()

    prompt_template = PromptTemplate(
        input_variables=['question', 'expected_ans', 'score', 'errors'],
        partial_variables={"format_instructions": format_instructions},
        template=guidelines_template
    )

    _input = prompt_template.format(
        question=question,
        expected_ans=expected_ans,
        score=total_score,
        errors=errors
    )

    try:
        response = await llm.ainvoke(_input)
        if hasattr(response, 'content'):
            response = response.content
        elif not isinstance(response, str):
            response = str(response)

        parsed_response = guidelines_parser.parse(response)
        return {
            "status": 200,
            "guidelines": str(parsed_response.get("guidelines", "No guidelines available"))
        }
    except Exception as e:
        logger.error(f"Error processing response: {str(e)}", exc_info=True)
        raise


async def enhance_question_and_answer(llm, question: str, expected_ans: str) -> dict:
    """
    Enhance the question and expected answer to be clear, concise, and direct.

    :param llm: The LLM instance to use for enhancing the content
    :param question: The question to enhance
    :param expected_ans: The expected answer to enhance
    """
    if not question or not expected_ans:
        logger.error("Provide a question and expected answer to enhance the content")
        raise InvalidInputError("question or expected_ans", f"question='{question}', expected_ans='{expected_ans}'")

    # Define response schema for enhanced content
    enhanced_content_schema = [
        ResponseSchema(name="enhanced_question", description="The enhanced question"),
        ResponseSchema(name="enhanced_expected_ans", description="The enhanced expected answer")
    ]
    enhanced_content_parser = StructuredOutputParser.from_response_schemas(enhanced_content_schema)
    format_instructions = enhanced_content_parser.get_format_instructions()

    prompt_template = PromptTemplate(
        input_variables=['question', 'expected_ans'],
        partial_variables={"format_instructions": format_instructions},
        template=qa_enhancement_template
    )

    _input = prompt_template.format(
        question=question,
        expected_ans=expected_ans
    )

    try:
        response = await llm.ainvoke(_input)
        if hasattr(response, 'content'):
            response = response.content
        elif not isinstance(response, str):
            response = str(response)

        parsed_response = enhanced_content_parser.parse(response)
        return {
            "status": 200,
            "enhanced_question": str(parsed_response.get("enhanced_question", "No enhanced question available")),
            "enhanced_expected_ans": str(
                parsed_response.get("enhanced_expected_ans", "No enhanced expected answer available"))
        }
    except Exception as e:
        logger.error(f"Error processing response: {str(e)}", exc_info=True)
        raise

async def score_fill_in_blank(llm, student_ans: str, expected_ans:str, total_score:float, question:str) -> dict:
    """
    Evaluate fill in the blank questions based on the expected answer and guidelines.

    :param llm: The LLM instance to use for scoring
    :param student_ans: The student's answer to evaluate
    :param expected_ans: The expected answer for comparison
    :param total_score: The total score to evaluate for
    :param question: The question
    """
    if not expected_ans or expected_ans.strip() == "":
        logger.error("Expected answer is empty or missing")
        raise InvalidInputError("expected_ans", f"expected_ans='{expected_ans}'")

    if not student_ans or student_ans.strip() == "":
        logger.error("Student answer is empty or missing")
        raise EmptyAnswerError()

    # Update response schemas to include 'rubric' and 'breakdown'
    response_schemas = [
        ResponseSchema(name="reason", description="A short and concise reason for the assigned score"),
        ResponseSchema(name="score", description="The assigned score as a floating point number"),
    ]

    output_parser = StructuredOutputParser.from_response_schemas(response_schemas)
    format_instructions = output_parser.get_format_instructions()
    question_section = f"\nQuestion:\n{question}\n" if question else "\n"

    prompt_template = PromptTemplate(
        input_variables=['student_ans', 'expected_ans', 'total_score'],
        partial_variables={
            "format_instructions": format_instructions,
            "question_section": question_section,
        },
        template=fill_in_the_blank_template
    )

    _input = prompt_template.format(
        student_ans=student_ans,
        expected_ans=expected_ans,
        total_score=total_score
    )

    try:
        response = await llm.ainvoke(_input)
        if hasattr(response, 'content'):
            response = response.content
        elif not isinstance(response, str):
            response = str(response)

        parsed_response = output_parser.parse(response)
        assert float(parsed_response.get("score", 0.0)) <= total_score, "Error: Score exceeds total score"
        return {
            "score": float(parsed_response.get("score", 0.0)), 
            "reason": str(parsed_response.get("reason", "No reason provided"))
        }
    except Exception as e:
        logger.error(f"Error processing response: {str(e)}", exc_info=True)
        raise


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
    result = asyncio.run(score_fill_in_blank(my_llm, my_student_ans, my_expected_ans, my_total_score, my_question))
    print(f"Fill in the blank scoring took: {time.time() - start} seconds")
    print(result)
