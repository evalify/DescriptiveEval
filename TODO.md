# TODO

1. Add Question-specific guidelines:
    This will give more context to the Evaluator-LLM
2. Give more detailed justification for Scoring
    Using something like CoT (increase test-time compute). Promote System 2 thinking
    (Use Reasoning models like o1?)
3. Add Past Evaluations in context memory
    This will allow consistency between multiple questions.
    This will prevent Evaluator LLM from giving different marks to similar answers from two students.
4. Add pre-planning on evaluation metrics on each question
    By allowing the LLM to plan in advance on how to evaluate a equation on advance,
    we can get consistent scoring across different responses

## Future Considerations

1. Implement bias mitigation strategies:
    Ensure the Evaluator-LLM provides fair assessments by minimizing potential biases.

2. Incorporate domain-specific knowledge:
    Enhance evaluations by integrating subject matter expertise relevant to the questions.