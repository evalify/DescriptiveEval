import os

from langchain_ollama import OllamaLLM
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate
from langchain.output_parsers import ResponseSchema, StructuredOutputParser
from enum import Enum
from dotenv import load_dotenv

load_dotenv()

from utils.templates import evaluation_template, guidelines_template, qa_enhancement_template


class LLMProvider(Enum):
    OLLAMA = "ollama"
    GROQ = "groq"


def get_llm(provider: LLMProvider = LLMProvider.OLLAMA, api_key=None, model_name=None):
    if provider == LLMProvider.OLLAMA:
        return OllamaLLM(model=model_name if model_name else "llama3.3")
    elif provider == LLMProvider.GROQ:
        return ChatGroq(
            api_key=api_key if api_key else os.getenv("GROQ_API_KEY"),
            model_name=model_name if model_name else "llama-3.3-70b-specdec",
            temperature=0.2,
        )
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")


# Initialize default LLM
current_provider = LLMProvider.GROQ  # Change to LLMProvider.OLLAMA if desired
llm = get_llm(current_provider)


def set_llm_provider(provider: LLMProvider):
    global llm, current_provider
    current_provider = provider
    llm = get_llm(provider)
    return llm


async def score(llm, student_ans, expected_ans, total_score, question=None, guidelines=None):
    if not expected_ans or expected_ans.strip() == "" or total_score < 1:
        return {
            "score": 0.0,
            "reason": f"Invalid input parameters: expected_ans='{expected_ans}', total_score='{total_score}'",
            "rubric": "No rubric available",
            "breakdown": "No breakdown available"
        }

    if not student_ans or student_ans.strip() == "":
        return {
            "score": 0.0,
            "reason": "Student answer is empty or missing",
            "rubric": "No rubric available",
            "breakdown": "No breakdown available"
        }

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
        input_variables=['student_ans', 'expected_ans', 'total_score'],
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
        total_score=total_score
    )

    try:
        response = await llm.ainvoke(_input)
        if hasattr(response, 'content'):
            response = response.content
        elif not isinstance(response, str):
            response = str(response)

        parsed_response = output_parser.parse(response)
        return {
            "rubric": str(parsed_response.get("rubric", "No rubric available")),
            "breakdown": str(parsed_response.get("breakdown", "No breakdown available")),
            "score": float(parsed_response.get("score", 0.0)),
            "reason": str(parsed_response.get("reason", "No reason provided"))
        }
    except Exception as e:
        return {
            "rubric": "Error: Could not generate rubric",
            "breakdown": "Error: Could not generate breakdown",
            "score": 0.0,
            "reason": f"Error processing response: {str(e)}"
        }


async def generate_guidelines(llm, question: str, expected_ans: str, total_score: int = 10) -> dict:
    if not question or not expected_ans:
        return {
            "guidelines": "Provide a question and expected answer to generate evaluation rubric/guidelines",
        }

    # Define response schema for guidelines
    guidelines_schema = [
        ResponseSchema(name="guidelines", description="The evaluation guidelines and criteria")
    ]
    guidelines_parser = StructuredOutputParser.from_response_schemas(guidelines_schema)
    format_instructions = guidelines_parser.get_format_instructions()

    prompt_template = PromptTemplate(
        input_variables=['question', 'expected_ans', 'score'],
        partial_variables={"format_instructions": format_instructions},
        template=guidelines_template
    )

    _input = prompt_template.format(
        question=question,
        expected_ans=expected_ans,
        score=total_score
    )

    try:
        response = await llm.ainvoke(_input)
        if hasattr(response, 'content'):
            response = response.content
        elif not isinstance(response, str):
            response = str(response)

        parsed_response = guidelines_parser.parse(response)
        return {
            "guidelines": str(parsed_response.get("guidelines", "No guidelines available"))
        }
    except Exception as e:
        return {
            "guidelines": f"Error processing response: {str(e)}"
        }


async def enhance_question_and_answer(llm, question: str, expected_ans: str) -> dict:
    if not question or not expected_ans:
        return {
            "enhanced_question": "Provide a question and expected answer to enhance the content",
            "enhanced_expected_ans": "Provide a question and expected answer to enhance the content",
        }

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
            "enhanced_question": str(parsed_response.get("enhanced_question", "No enhanced question available")),
            "enhanced_expected_ans": str(
                parsed_response.get("enhanced_expected_ans", "No enhanced expected answer available"))
        }
    except Exception as e:
        return {
            "enhanced_question": f"Error processing response: {str(e)}",
            "enhanced_expected_ans": f"Error processing response: {str(e)}"
        }
