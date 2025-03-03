from fastapi import APIRouter, HTTPException, Depends
from .service import (
    score,
    generate_guidelines,
    enhance_question_and_answer,
)
from .models import QueryRequest, GuidelinesRequest, QAEnhancementRequest
from app.core.logger import logger
from app.core.exceptions import InvalidInputError
from app.core.dependencies import get_llm_dependency, get_micro_llm_dependency
from app.config.constants import MAX_RETRIES
from app.config.enums import EvaluationStatus
import uuid

# Router
router = APIRouter(prefix="/scoring", tags=["Scoring"])


@router.post("/score")
async def get_score_response(request: QueryRequest, llm=Depends(get_llm_dependency)):
    trace_id = uuid.uuid4()
    logger.info(
        f"[{trace_id}] Scoring request received for question: {request.question[:100]}..."
    )

    try:
        result = await score(
            llm=llm,
            student_ans=request.student_ans,
            expected_ans=request.expected_ans,
            total_score=request.total_score,
            question=request.question,
            guidelines=request.guidelines,  # Pass guidelines if provided
        )

        if result["status"] == EvaluationStatus.SUCCESS:
            logger.info(f"[{trace_id}] Scoring complete. Score: {result.get('score')}")
            return result
        else:
            # Mild errors
            if result["status"] == EvaluationStatus.EMPTY_ANSWER:
                logger.warning(
                    f"[{trace_id}] Empty answer error: {result.get('error')}"
                )
            elif result["status"] == EvaluationStatus.INVALID_INPUT:
                logger.warning(
                    f"[{trace_id}] Invalid input error: {result.get('error')}"
                )
            # Severe errors
            elif result["status"] == EvaluationStatus.LLM_ERROR:
                logger.error(
                    f"[{trace_id}] LLM processing error: {result.get('error')}"
                )
            elif result["status"] == EvaluationStatus.PARSE_ERROR:
                logger.error(
                    f"[{trace_id}] Response parsing error: {result.get('error')}"
                )
            else:
                logger.error(f"[{trace_id}] Scoring failed: {result.get('error')}")
            raise HTTPException(
                status_code=result["status"], detail=result.get("error")
            )
    except Exception:
        logger.error(f"[{trace_id}] Error processing scoring request", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/generate-guidelines")
async def generate_guidelines_api(
    request: GuidelinesRequest, llm=Depends(get_micro_llm_dependency)
):
    trace_id = uuid.uuid4()
    logger.info(
        f"[{trace_id}] Guidelines generation request received for question: {request.question[:100]}..."
    )

    try:
        errors = []
        guidelines_result = {}
        for attempt in range(MAX_RETRIES):
            guidelines_result = await generate_guidelines(
                llm,
                question=request.question or "",
                expected_ans=request.expected_ans or "",
                total_score=request.total_score or 10,
                errors=errors,
            )
            if guidelines_result.get("status") != 200:
                error_msg = guidelines_result.get("error", "Unknown Error")
                logger.warning(
                    f"[{trace_id}] Attempt {attempt + 1}/{MAX_RETRIES}: Failed to generate guidelines for api request {error_msg}"
                )
                errors.append(error_msg)
                continue
            else:
                logger.info(f"[{trace_id}] Guidelines generated successfully")
            break
        return guidelines_result
    except InvalidInputError as e:
        logger.error(f"[{trace_id}] Invalid input error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.error(f"[{trace_id}] Error generating guidelines", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/enhance-qa")
async def enhance_qa(
    request: QAEnhancementRequest, llm=Depends(get_micro_llm_dependency)
):
    try:
        result = await enhance_question_and_answer(
            llm, question=request.question, expected_ans=request.expected_ans
        )
        return result
    except InvalidInputError as e:
        logger.error(f"Invalid input error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.error("Error enhancing question and answer", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
