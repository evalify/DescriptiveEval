from langchain_ollama import OllamaLLM
from langchain_groq import ChatGroq
from langchain import PromptTemplate
import json
from langchain.output_parsers import ResponseSchema, StructuredOutputParser
import os
from enum import Enum

from dotenv import load_dotenv
load_dotenv()

class LLMProvider(Enum):
    OLLAMA = "ollama"
    GROQ = "groq"

def get_llm(provider: LLMProvider = LLMProvider.OLLAMA):
    if provider == LLMProvider.OLLAMA:
        return OllamaLLM(model="llama3.1")
    elif provider == LLMProvider.GROQ:
        return ChatGroq(
            api_key=os.getenv("GROQ_API_KEY"),
            model_name="llama-3.3-70b-versatile"
        )
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")

# Initialize default LLM
current_provider = LLMProvider.GROQ  # Can be changed to LLMProvider.GROQ
llm = get_llm(current_provider)

response_schemas = [
    ResponseSchema(name="score", description="The assigned score as an integer"),
    ResponseSchema(name="reason", description="A short and concise reason for the assigned score")
]

output_parser = StructuredOutputParser.from_response_schemas(response_schemas)
format_instructions = output_parser.get_format_instructions()

template = '''
You are an expert evaluator. Your task is to assess the student's answer based solely on the expected answer provided. Evaluate the student's answer and assign a score out of the total score. Additionally, provide a short and concise reason for the score, focusing only on the alignment between the student's answer and the expected answer. Do not consider any factors outside the provided expected answer.

{format_instructions}

Student's Answer: {student_ans}

Expected Answer: {expected_ans}

Total Score: {total_score}
'''

prompt = PromptTemplate(
    input_variables=['student_ans', 'expected_ans', 'total_score'],
    partial_variables={"format_instructions": format_instructions},
    template=template
)

def set_llm_provider(provider: LLMProvider):
    global llm, current_provider
    current_provider = provider
    llm = get_llm(provider)
    return llm

def score(llm, student_ans, expected_ans, total_score):
    _input = prompt.format(
        student_ans=student_ans,
        expected_ans=expected_ans,
        total_score=total_score
    )
    response = llm(_input)
    try:
        parsed_response = output_parser.parse(response)
        return json.dumps(parsed_response, indent=4)
    except Exception as e:
        raise ValueError(f"Failed to parse LLM response: {e}")
