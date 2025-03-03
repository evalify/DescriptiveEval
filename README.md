# DescEval

## Description

DescEval is a FastAPI application and acts as the Evaluation backend for Evalify.

## Installation

1. Clone the repository:
    - git clone
2. Install uv for easy package management:
    - pip install uv
3. Create a virtual environment:
    - uv venv
4. Install the required packages:
    - uv sync --reinstall

Optional: Setup ruff pre-commit hook for linting:

- pre-commit install

## Usage

1. Start the FastAPI server:
    - python -m app.main

## Testing

Run tests with pytest (including async tests):
    - pytest
