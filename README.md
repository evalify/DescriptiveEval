# Descriptive Evaluation Using LLMs

This repository demonstrates how to evaluate descriptive answers using large language models (LLMs). It contains:

- A set of database integration files (CockroachDB and MongoDB).
- A FastAPI server exposing a simple scoring endpoint for descriptive answers.
- Example tests showcasing various LLM providers and test scenarios.

## Features

- Flexible LLM provider switching between Ollama and Groq.
- Rubric generation and score breakdown for each evaluated response.
- Async-based FastAPI endpoints for generating guidelines and scoring answers.

## Prerequisites

- Python 3.9+
- Install dependencies:
    - pip install -r requirements.txt
- Environment variables for CockroachDB, MongoDB, and any required LLM API keys.

## Usage

1. Start the FastAPI server:
    - python app.py
2. Send requests to the endpoints (/score, /generate-guidelines, etc.).
3. To update the LLM provider, use the "/set-provider" POST endpoint.

## Testing

- Run tests with pytest (including async tests):
    - pytest

## Notes

- This project is in WIP status and may contain bugs.
- The evaluation focuses on content relevance and correctness, ignoring user attempts to bypass guidelines.
