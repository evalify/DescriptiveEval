from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from app.api.misc.service import generate_excel_report, generate_excel_class_report
from app.core.logger import logger
from .models import CourseReportRequest, ClassReportRequest
from .utils import get_semester_id_from_class_id, get_semester_id_from_course_id
import time

router = APIRouter(prefix="/misc", tags=["Miscellaneous"])


@router.post("/course-report")
async def get_course_report(request: CourseReportRequest):
    """
    Generate and stream an Excel report for a course.

    Returns an Excel file with student scores for all quizzes in the course.
    Allows filtering by date range using start_date and end_date parameters (format: YYYY-MM-DD).
    The exclude_dates parameter determines whether to include or exclude quizzes in the specified date range.
    Alternatively, you can provide specific_dates as a list of exact dates to include or exclude.
    You can also control the "Average of Best N" calculation with best_avg_count and normalization_mark.
    """
    course_id = request.course_id
    start_date = request.start_date
    end_date = request.end_date
    exclude_dates = request.exclude_dates
    specific_dates = request.specific_dates
    best_avg_count = request.best_avg_count
    normalization_mark = request.normalization_mark

    logger.debug(
        f"Received request to generate course report for course_id: {course_id}, "
        f"timeframe: {start_date} to {end_date}, exclude_dates: {exclude_dates}, "
        f"specific_dates: {specific_dates}, best_avg_count: {best_avg_count}, "
        f"normalization_mark: {normalization_mark}"
    )
    try:
        # Generate the Excel report
        logger.info(f"Generating Excel report for course: {course_id}")
        excel_data = await generate_excel_report(
            course_id,
            save_to_file=True,
            start_date=start_date,
            end_date=end_date,
            exclude_dates=exclude_dates,
            specific_dates=specific_dates,
            best_avg_count=best_avg_count,
            normalization_mark=normalization_mark,
        )
        course_code = excel_data.get("course_code")

        # Create filename with course code, timeframe and timestamp for the download
        timeframe_text = ""
        if specific_dates:
            date_action = "excluding" if exclude_dates else "including"
            dates_str = "-".join([d.replace("-", "") for d in specific_dates[:3]])
            if len(specific_dates) > 3:
                dates_str += f"_and_{len(specific_dates) - 3}_more"
            timeframe_text = f"_{date_action}_specific_dates_{dates_str}"
        elif start_date or end_date:
            exclude_text = "excluding" if exclude_dates else "from"
            if start_date and end_date:
                timeframe_text = f"_{exclude_text}_{start_date}_to_{end_date}"
            elif start_date:
                timeframe_text = f"_{exclude_text}_{start_date}_onwards"
            elif end_date:
                timeframe_text = f"_{exclude_text}_until_{end_date}"

        filename = f"{course_code}{timeframe_text}_course_report_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"
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
    Allows filtering by date range using start_date and end_date parameters (format: YYYY-MM-DD).
    The exclude_dates parameter determines whether to include or exclude quizzes in the specified date range.
    The specific_dates parameter allows filtering by a specific list of dates.
    You can also control the "Average of Best N" calculation with best_avg_count and normalization_mark.
    """
    class_id = request.class_id
    start_date = request.start_date
    end_date = request.end_date
    exclude_dates = request.exclude_dates
    specific_dates = request.specific_dates
    best_avg_count = request.best_avg_count
    normalization_mark = request.normalization_mark

    logger.debug(
        f"Received request to generate class report for class_id: {class_id}, "
        f"timeframe: {start_date} to {end_date}, exclude_dates: {exclude_dates}, "
        f"specific_dates: {specific_dates}, best_avg_count: {best_avg_count}, "
        f"normalization_mark: {normalization_mark}"
    )
    try:
        # Generate the Excel report for all courses in the class
        logger.info(f"Generating Excel report for class: {class_id}")
        response = await generate_excel_class_report(
            class_id,
            save_to_file=False,
            start_date=start_date,
            end_date=end_date,
            exclude_dates=exclude_dates,
            specific_dates=specific_dates,
            best_avg_count=best_avg_count,
            normalization_mark=normalization_mark,
        )
        excel_data = response.get("file")
        class_name = response.get("class_name")
        if not excel_data:
            logger.warning(f"No courses found for class: {class_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No courses found for class: {class_id}",
            )

        # Create filename with class ID, timeframe and timestamp for the download
        timeframe_text = ""
        if specific_dates:
            dates_str = "-".join([d.replace("-", "") for d in specific_dates[:3]])
            if len(specific_dates) > 3:
                dates_str += f"_plus_{len(specific_dates) - 3}_more"
            exclude_text = "excluding" if exclude_dates else "only"
            timeframe_text = f"_{exclude_text}_dates_{dates_str}"
        elif start_date or end_date:
            exclude_text = "excluding" if exclude_dates else "from"
            if start_date and end_date:
                timeframe_text = f"_{exclude_text}_{start_date}_to_{end_date}"
            elif start_date:
                timeframe_text = f"_{exclude_text}_{start_date}_onwards"
            elif end_date:
                timeframe_text = f"_{exclude_text}_until_{end_date}"

        filename = f"class_{class_name}{timeframe_text}_report_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"
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


specific_dates_override = {
    "S4": [
        "2025-03-17",
        "2025-03-18",
        "2025-03-24",
        "2025-03-25",
        "2025-03-26",
        "2025-03-27",
        "2025-03-28",
        "2025-03-29",
        "2025-04-01",
        "2025-04-02",
        "2025-04-03",
        "2025-04-04",
        "2025-04-07",
    ],
    "S2": [
        "2025-03-17",
        "2025-03-18",
        "2025-03-24",
        "2025-03-25",
        "2025-03-26",
        "2025-03-27",
        "2025-03-28",
        "2025-03-29",
        "2025-04-01",
        "2025-04-02",
        "2025-04-03",
        "2025-04-04",
        "2025-04-05",
        "2025-04-07",
        "2025-04-11",
        "2025-04-12",
    ],
}


@router.post("/course-report-filtered")
async def get_course_report_filtered(request: CourseReportRequest):
    """
    Generate and stream an Excel report for a course, overriding specific_dates based on semester.

    Returns an Excel file with student scores for all quizzes in the course.
    Allows filtering by date range using start_date and end_date parameters (format: YYYY-MM-DD).
    The exclude_dates parameter determines whether to include or exclude quizzes in the specified date range.
    The specific_dates parameter from the request is IGNORED and overridden based on the course's semester.
    You can also control the "Average of Best N" calculation with best_avg_count and normalization_mark.
    """
    # Determine semester and override specific_dates
    course_id = request.course_id
    semester_id = await get_semester_id_from_course_id(course_id)
    if not semester_id:
        logger.error(f"Semester ID not found for course {course_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Semester ID not found for course {course_id}",
        )
    semester_id = semester_id.strip().upper()
    specific_dates = specific_dates_override.get(semester_id)

    logger.debug(
        f"Received request for filtered course report for course_id: {course_id}, "
        f"timeframe: {request.start_date} to {request.end_date}, exclude_dates: {request.exclude_dates}, "
        f"best_avg_count: {request.best_avg_count}, normalization_mark: {request.normalization_mark}. "
        f"Determined semester: {semester_id}. Overriding specific_dates with: {specific_dates}"
    )

    if specific_dates is None:
        logger.warning(
            f"No specific dates override found for semester {semester_id} (course {course_id}). "
            f"Proceeding without specific_dates filter."
        )

    # Create a modified copy of the request with overridden specific_dates
    modified_request = CourseReportRequest(
        course_id=request.course_id,
        start_date=request.start_date,
        end_date=request.end_date,
        exclude_dates=request.exclude_dates,
        specific_dates=specific_dates,  # Use overridden dates
        best_avg_count=request.best_avg_count,
        normalization_mark=request.normalization_mark,
    )

    # Forward to the original route handler
    logger.info(
        f"Forwarding to course-report with filtered dates for semester {semester_id}"
    )
    return await get_course_report(modified_request)


@router.post("/class-report-filtered")
async def get_class_report_filtered(request: ClassReportRequest):
    """
    Generate and stream an Excel report for all courses in a class, overriding specific_dates based on semester.

    Returns a single Excel file with multiple sheets, one for each course in the class.
    Each sheet contains student scores for all quizzes in that course.
    Allows filtering by date range using start_date and end_date parameters (format: YYYY-MM-DD).
    The exclude_dates parameter determines whether to include or exclude quizzes in the specified date range.
    The specific_dates parameter from the request is IGNORED and overridden based on the class's semester.
    You can also control the "Average of Best N" calculation with best_avg_count and normalization_mark.
    """
    class_id = request.class_id

    # Determine semester and override specific_dates
    semester_id = await get_semester_id_from_class_id(class_id)
    if not semester_id:
        logger.error(f"Semester ID not found for class {class_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Semester ID not found for class {class_id}",
        )
    semester_id = semester_id.strip().upper()
    specific_dates = specific_dates_override.get(semester_id)

    logger.debug(
        f"Received request for filtered class report for class_id: {class_id}, "
        f"timeframe: {request.start_date} to {request.end_date}, exclude_dates: {request.exclude_dates}, "
        f"best_avg_count: {request.best_avg_count}, normalization_mark: {request.normalization_mark}. "
        f"Determined semester: {semester_id}. Overriding specific_dates with: {specific_dates}"
    )

    if specific_dates is None:
        logger.warning(
            f"No specific dates override found for semester {semester_id} (class {class_id}). "
            f"Proceeding without specific_dates filter."
        )

    # Create a modified copy of the request with overridden specific_dates
    modified_request = ClassReportRequest(
        class_id=request.class_id,
        start_date=request.start_date,
        end_date=request.end_date,
        exclude_dates=request.exclude_dates,
        specific_dates=specific_dates,  # Use overridden dates
        best_avg_count=request.best_avg_count,
        normalization_mark=request.normalization_mark,
    )

    # Forward to the original route handler
    logger.info(
        f"Forwarding to class-report with filtered dates for semester {semester_id}"
    )
    return await get_class_report(modified_request)
