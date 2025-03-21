from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from app.api.misc.service import generate_excel_report
from app.core.logger import logger

router = APIRouter(prefix="/misc", tags=["Miscellaneous"])


@router.get("/course-report/{course_id}")
async def get_course_report(course_id: str):
    """
    Generate and stream an Excel report for a course.

    Returns an Excel file with student scores for all quizzes in the course.
    """
    logger.debug(
        f"Received request to generate course report for course_id: {course_id}"
    )
    try:
        # Generate the Excel report
        logger.info(f"Generating Excel report for course: {course_id}")
        excel_data = await generate_excel_report(course_id)

        # Create filename with course ID for the download
        filename = f"course_{course_id}_report.xlsx"
        logger.debug(f"Created filename: {filename}")

        # Return the Excel file as a streaming response
        logger.info(f"Streaming Excel report for course: {course_id}")
        return StreamingResponse(
            excel_data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.error(f"Error generating report for course {course_id}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating report: {str(e)}",
        )
