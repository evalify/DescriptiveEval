# TO-DO

## RealTime

- [x] Modularize Code in app.py, check [link](https://www.perplexity.ai/search/how-to-seperate-fastapi-app-sa-g3nbxnGiSVuFmxorRrnWEA)
- [ ] Add dynamic batch size for evaluation
- [x] Dashboard for monitoring evaluations
- [x] Add polling for evaluation status
- [x] Fix empty response from student is considered critical and kills the evaluation

## High Priority

- [ ] Add API for retrieving available models (Hard-Coded but validated from list of available models in ollama)
- [ ] Add model selection support
- [x] Add QuizReport aka Statistics - follow schema refer [route](https://github.com/Aksaykanthan/evalify/blob/main/src/app/api/staff/result/route.ts)
- [x] Add Negative marking support - flags from evaluation settings
- [x] Add backward compatability for old schema (where quiz_result)
- [x] Add isEvaluated in Quiz & QuizResult
- [x] Partial Marking for MCQs
- [x] Add Queue Management for Evaluation
- [x] How to stop duplicate quizId running on two workers when two requests comes ? and what to do if the worker terminates unexpectedly?
- [x] Can you add more logger calls whereever necessary? I want to have more information to debug. Can you improve quiz wise logging too?
- [x] Is it possible to implement quiz wise logging? So I can clearly see what's happening in each quiz's evaluation seperately? How about writing it in a file in quizId/ ?

## Medium Priority

- [x] Add Get Route for /status retrival
  1. Unevaluated
  2. Pending
  3. Evaluating
  4. Completed
- [ ] Add support for selective (question-id) re-evaluation of questions
- [x] Centralize schema for evaluation

## Low Priority

- [ ] Write Documentation
- [ ] Check out VideoPoet
- [ ] Update README.md
- [ ] Add strict checking/case sensitivity support - flags from mongodb question settings (strictMatch)
- [ ] Partial marking/Absolute marking for Coding questions
- [ ] Add support for LiteLLM
- [x] Setup openwebui in EvalifyVM

## Descriptive Evaluation

- [ ] Tweak Guidelines generation to be more specific
- [ ] Fix /score to allow full marks for good answers
- [x] Add Tests for new features
- [ ] Handle "Error processing response: Got invalid JSON object. Error: Invalid \escape: line 2 column 103 (char 104)
  For troubleshooting,
  visit: [LangChain/OutputParsingFailure](https://python.langchain.com/docs/troubleshooting/errors/OUTPUT_PARSING_FAILURE)"
- [ ] Add Past Evaluations in context memory
  This will allow consistency between multiple questions.
  This will prevent Evaluator LLM from giving different marks to similar answers from two students.
- [x] Add Question-specific guidelines:
  This will give more context to the Evaluator-LLM
- [ ] Give more detailed justification for Scoring
  Using something like CoT (increase test-time compute). Promote System 2 thinking
  (Use Reasoning models like r1?)

- [x] Add pre-planning on evaluation metrics on each question
  By allowing the LLM to plan in advance on how to evaluate an equation in advance,
  we can get consistent scoring across different responses

## Future Considerations

1. Implement bias mitigation strategies:
   Ensure the Evaluator-LLM provides fair assessments by minimizing potential biases.

2. Incorporate domain-specific knowledge:
   Enhance evaluations by integrating subject expertise relevant to the questions.
