from fastapi import APIRouter, HTTPException, Depends
from .scoring import (
    score,
    generate_guidelines,
    enhance_question_and_answer,
)
from .models import QueryRequest, GuidelinesRequest, QAEnhancementRequest
from app.core.logger import logger
from app.core.exceptions import InvalidInputError, EmptyAnswerError
from app.core.dependencies import get_llm_dependency, get_micro_llm_dependency
import uuid
import os

# Router
router = APIRouter(prefix="/scoring", tags=["Scoring"])


@router.post("/score")
async def get_response(request: QueryRequest, llm=Depends(get_llm_dependency)):
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
        logger.info(f"[{trace_id}] Scoring complete. Score: {result.get('score')}")
        return result
    except InvalidInputError as e:
        logger.error(f"[{trace_id}] Invalid input error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except EmptyAnswerError as e:
        logger.error(f"[{trace_id}] Empty answer error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
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
        MAX_RETRIES = int(
            os.getenv("MAX_RETRIES", 10)
        )  # TODO: Move Constants to constant.py
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
