# TODO

- Tweak Guidelines generation to be more specific
- Fix /score to allow full marks for good answers
- Add Tests for new features
- Handle "Error processing response: Got invalid JSON object. Error: Invalid \escape: line 2 column 103 (char 104)
For troubleshooting, visit: [LangChain/OutputParsingFailure](https://python.langchain.com/docs/troubleshooting/errors/OUTPUT_PARSING_FAILURE)"
- Add Past Evaluations in context memory
This will allow consistency between multiple questions.
This will prevent Evaluator LLM from giving different marks to similar answers from two students.
- [x] Add Question-specific guidelines:
This will give more context to the Evaluator-LLM
- Give more detailed justification for Scoring
Using something like CoT (increase test-time compute). Promote System 2 thinking
(Use Reasoning models like o1?)

- [x] Add pre-planning on evaluation metrics on each question
By allowing the LLM to plan in advance on how to evaluate a equation on advance,
we can get consistent scoring across different responses

## Future Considerations

1. Implement bias mitigation strategies:
   Ensure the Evaluator-LLM provides fair assessments by minimizing potential biases.

2. Incorporate domain-specific knowledge:
   Enhance evaluations by integrating subject matter expertise relevant to the questions.
