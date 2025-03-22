from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from app.api.misc.service import generate_excel_report, generate_excel_class_report
from app.core.logger import logger
from .models import CourseReportRequest, ClassReportRequest
import time

router = APIRouter(prefix="/misc", tags=["Miscellaneous"])


@router.post("/course-report")
async def get_course_report(request: CourseReportRequest):
    """
    Generate and stream an Excel report for a course.

    Returns an Excel file with student scores for all quizzes in the course.
    """
    course_id = request.course_id
    logger.debug(
        f"Received request to generate course report for course_id: {course_id}"
    )
    try:
        # Generate the Excel report
        logger.info(f"Generating Excel report for course: {course_id}")
        excel_data = await generate_excel_report(course_id)
        course_code = excel_data.get("course_code")
        # Create filename with course code and timestamp for the download
        filename = f"{course_code}_course_report_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"
        logger.debug(f"Created filename: {filename}")

        # Return the Excel file as a streaming response
        logger.info(f"Streaming Excel report for course: {course_id}")
        return StreamingResponse(
            excel_data["file"],
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.error(f"Error generating report for course {course_id}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating report: {str(e)}",
        )


@router.post("/class-report")
async def get_class_report(request: ClassReportRequest):
    """
    Generate and stream an Excel report for all courses in a class.

    Returns a single Excel file with multiple sheets, one for each course in the class.
    Each sheet contains student scores for all quizzes in that course.
    """
    class_id = request.class_id

    logger.debug(f"Received request to generate class report for class_id: {class_id}")
    try:
        # Generate the Excel report for all courses in the class
        logger.info(f"Generating Excel report for class: {class_id}")
        response = await generate_excel_class_report(class_id, save_to_file=False)
        excel_data = response.get("file")
        class_name = response.get("class_name")
        if not excel_data:
            logger.warning(f"No courses found for class: {class_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No courses found for class: {class_id}",
            )

        # Create filename with class ID and timestamp for the download
        filename = f"class_{class_name}_report_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"
        logger.debug(f"Created filename: {filename}")

        # Return the Excel file as a streaming response
        logger.info(f"Streaming Excel report for class: {class_id}")
        return StreamingResponse(
            excel_data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error generating report for class {class_id}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating report: {str(e)}",
        )
