# TO-DO

## RealTime

- [ ] Redirect old routes for backwards compatibility
- [ ] Add support for selective (question-id) re-evaluation of questions
- [ ] Add dynamic batch size for evaluation
- [ ] Persist completed jobs in 4040 dashboard
- [ ] Add more info for failed jobs
- [ ] Add retry failed jobs in 4040 dashboard
- [ ] Token Metrics for LLMs
- [ ] Killed jobs should be in canceled, not failed

## High Priority

- [ ] Fix Cache (check override_cache's usage)

## Medium Priority

- [ ] Separate worker for MCQ and LLM

## Low Priority

- [ ] Add Tests for new features
- [ ] Add API for retrieving available models (Hard-Coded but validated from list of available models in ollama)
- [ ] Add model selection support
- [ ] Write Documentation
- [ ] Update README.md
- [ ] Add strict checking/case sensitivity support - flags from mongodb question settings (strictMatch)
- [ ] Partial marking/Absolute marking for Coding questions
- [ ] Add support for LiteLLM

## Descriptive Evaluation

- [ ] Tweak Guidelines generation to be more specific
- [ ] Fix /score to allow full marks for good answers
- [ ] Handle "Error processing response: Got invalid JSON object. Error: Invalid \escape: line 2 column 103 (char 104)
  For troubleshooting,
  visit: [LangChain/OutputParsingFailure](https://python.langchain.com/docs/troubleshooting/errors/OUTPUT_PARSING_FAILURE)"
- [ ] Add Past Evaluations in context memory
  This will allow consistency between multiple questions.
  This will prevent Evaluator LLM from giving different marks to similar answers from two students.

- [ ] Give more detailed justification for Scoring
  Using something like CoT (increase test-time compute). Promote System 2 thinking
  (Use Reasoning models like r1?)

## Future Considerations

1. Implement bias mitigation strategies:
   Ensure the Evaluator-LLM provides fair assessments by minimizing potential biases.

2. Incorporate domain-specific knowledge:
   Enhance evaluations by integrating subject expertise relevant to the questions.

## Completed

- [x] Modularize Code in app.py, check [link](https://www.perplexity.ai/search/how-to-seperate-fastapi-app-sa-g3nbxnGiSVuFmxorRrnWEA)
- [x] Dashboard for monitoring evaluations
- [x] Add polling for evaluation status
- [x] Fix empty response from student is considered critical and kills the evaluation
- [x] Add QuizReport aka Statistics - follow schema refer [route](https://github.com/Aksaykanthan/evalify/blob/main/src/app/api/staff/result/route.ts)
- [x] Add Negative marking support - flags from evaluation settings
- [x] Add backward compatability for old schema (where quiz_result)
- [x] Add isEvaluated in Quiz & QuizResult
- [x] Partial Marking for MCQs
- [x] Add Queue Management for Evaluation
- [x] How to stop duplicate quizId running on two workers when two requests comes ? and what to do if the worker terminates unexpectedly?
- [x] Can you add more logger calls whereever necessary? I want to have more information to debug. Can you improve quiz wise logging too?
- [x] Is it possible to implement quiz wise logging? So I can clearly see what's happening in each quiz's evaluation seperately? How about writing it in a file in quizId/ ?

- [x] Add Get Route for /status retrieval
  1. Unevaluated
  2. Pending
  3. Evaluating
  4. Completed
- [x] Centralize schema for evaluation
- [x] Setup openwebui in EvalifyVM
- [x] Add Question-specific guidelines:
  This will give more context to the Evaluator-LLM

- [x] Add pre-planning on evaluation metrics on each question
  By allowing the LLM to plan in advance on how to evaluate an equation in advance,
  we can get consistent scoring across different responses
