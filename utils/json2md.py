"""This module helps to print the descriptive evaluation in markdown format"""

from evaluation_api import get_all_questions #TODO: Update references to new version of evaluation_api
import json

# pandoc -s -V geometry:margin=1in --pdf-engine=xelatex -V mainfont="JetBrains Mono" -o DescEval.pdf Descriptive_Eval.md
question_id = "67809dc7af8badd513d4ae73"
with open("../data/json/la_desc_questions.json") as f:
    questions = json.load(f)
    for i in questions:
        if i["_id"] == question_id:
            question = i["question"]
            guidelines = i["guidelines"]
            expected_answer = i["explanation"]
            break

with open("../data/json/quiz_responses_evaluated.json") as f:
    descriptive_responses = [{
        'studentId': i["studentId"],
        'response': i["responses"][question_id][0],
        'score': i["questionMarks"][question_id],
        'remark': i["remarks"][question_id],
        'total_score': 8
    } for i in json.load(f) if i["responses"].get(question_id) is not None]


def create_markdown_file(responses, output_filename):
    with open(output_filename, 'w') as f:
        f.write("# Descriptive Evaluation\n\n")
        f.write("\tDescEval: v0.2-alpha\n")
        f.write("\tPlease note this evaluation method is still in testing phase\n")
        f.write("\tIf you find any issues, please report to us.\n")
        f.write(
            "\tThe Guidelines are provided by the instructor, and\n\tan LLM will help in the initial draft of guideline writing.\n\n")
        f.write("## Configuration\n")
        f.write("\tQuiz ID: cm5ly4fgu00b28pe3sx17kiur\n")
        f.write("\tLLM Used: llama3.3-70b (SpecDec/Versatile)\n")
        f.write(f"\tTotal Responses: {len(responses)}\n")
        f.write(f"## Guidelines:\n{guidelines}\n\n")
        f.write("## Question\n")
        f.write(f"{question}\n\n")
        f.write("## Expected Answer\n")
        f.write(f"{expected_answer}\n---\n\n")
        for student in responses:
            f.write(f"## Student Id : {student['studentId']}\n")
            f.write(f"### Response:\n \"{student['response'].strip()}\"\n\n")
            f.write(f"### Score:\n **{student['score']}/{student['total_score']}**\n\n")
            f.write(student['remark'].replace('\n## ', '\n\n### '))
            f.write("---\n\n")


create_markdown_file(descriptive_responses, "../data/markdown/Descriptive_Eval_symmetric_all.md")
