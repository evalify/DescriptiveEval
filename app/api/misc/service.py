from app.database.postgres import get_db_cursor
import pandas as pd
from io import BytesIO
import os
from datetime import datetime
from pytz import timezone
from app.core.logger import logger


async def fetch_course_report(course_id: str):
    logger.debug(f"Fetching course report for course ID: {course_id}")
    query = """
    SELECT 
        s."id" AS "studentId",
        u."name" AS "studentName",  
        u."rollNo" AS "studentRollNo",
        s."classId",
        cq."B" AS "quizId",
        q."title" AS "quizTitle",
        q."startTime" AS "quizStartTime",
        qr."score",
        qr."totalScore"
    FROM "Student" s
    JOIN "User" u ON s."id" = u."id" AND u."role" = 'STUDENT'
    JOIN "Course" c ON s."classId" = c."classId"
    JOIN "_CourseToQuiz" cq ON c."id" = cq."A"
    LEFT JOIN "Quiz" q ON cq."B" = q."id"
    LEFT JOIN "QuizResult" qr ON s."id" = qr."studentId" AND cq."B" = qr."quizId"
    WHERE c."id" = %s
    ORDER BY s."id", cq."B";
    """
    with get_db_cursor() as (cursor, conn):
        cursor.execute(query, (course_id,))
        rows = cursor.fetchall()
        logger.debug(f"Query executed, {len(rows)} rows fetched.")

    # Dictionary to store student data
    students_data = {}
    quiz_info = {}
    class_id = None

    # First, gather all quizzes and their details
    for row in rows:
        quiz_id = row["quizId"]
        if quiz_id not in quiz_info:
            quiz_info[quiz_id] = {
                "title": row["quizTitle"] or f"Quiz {quiz_id}",
                "totalScore": row["totalScore"],
                "startTime": row["quizStartTime"],
            }
            logger.debug(f"Quiz ID {quiz_id} added to quiz_info.")
        else:
            # Check if total score is consistent
            if (
                row["totalScore"] is not None
                and quiz_info[quiz_id]["totalScore"] is not None
            ):
                if row["totalScore"] != quiz_info[quiz_id]["totalScore"]:
                    raise ValueError(f"Inconsistent total scores for quiz {quiz_id}")

        if class_id is None and row["classId"]:
            class_id = row["classId"]
            logger.debug(f"Class ID set to {class_id}.")

    # Now process student data
    for row in rows:
        student_id = row["studentId"]
        quiz_id = row["quizId"]

        if student_id not in students_data:
            students_data[student_id] = {
                "Student Name": row.get("studentName", ""),
                "Roll Number": row.get("studentRollNo", ""),
            }
            logger.debug(f"Student ID {student_id} added to students_data.")

        # Add quiz score info (only score, not total)
        students_data[student_id][quiz_info[quiz_id]["title"]] = row["score"]

    # Convert to list for dataframe
    students_list = list(students_data.values())
    logger.debug(f"Converted students_data to list, {len(students_list)} students.")

    # Process quiz info to include formatted dates
    quiz_details = {}
    for quiz_id, info in quiz_info.items():
        title = info["title"]
        quiz_details[title] = {
            "totalScore": info["totalScore"],
            "date": format_date(info["startTime"]) if info["startTime"] else "N/A",
        }
    logger.debug(f"Processed quiz details, {len(quiz_details)} quizzes.")

    return {
        "students": students_list,
        "quiz_details": quiz_details,
        "class_id": class_id,
        "student_count": len(students_list),
        "quiz_count": len(quiz_info),
    }


def format_date(date_str):
    """Convert UTC datetime string to IST date string"""
    if not date_str:
        return "N/A"
    try:
        # Check if date_str is already a datetime object
        if isinstance(date_str, str):
            # Parse the datetime string
            utc_dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        else:
            utc_dt = date_str
        # Convert to IST (UTC+5:30)
        ist = timezone("Asia/Kolkata")
        ist_dt = utc_dt.replace(tzinfo=timezone("UTC")).astimezone(ist)
        # Format as date string
        return ist_dt.strftime("%d/%m/%Y")
    except Exception as e:
        print(f"Error formatting date: {e}")
        return date_str


async def generate_excel_report(course_id: str, save_to_file: bool = True):
    """
    Generate an Excel report for the course.
    Returns a BytesIO object containing the Excel file.
    """
    logger.debug(
        f"Generating Excel report for course ID: {course_id}, save_to_file: {save_to_file}"
    )
    # Fetch the course report data
    report_data = await fetch_course_report(course_id)
    students_data = report_data["students"]
    quiz_details = report_data["quiz_details"]
    class_id = report_data["class_id"]
    student_count = report_data["student_count"]
    quiz_count = report_data["quiz_count"]

    # Create DataFrame for student data
    df = pd.DataFrame(students_data)
    logger.debug("DataFrame created from student data.")

    # Create Excel file in memory
    output = BytesIO()
    logger.debug("BytesIO object created for Excel file.")

    # Get course name for the report title
    with get_db_cursor() as (cursor, conn):
        cursor.execute(
            'SELECT "name", "code" FROM "Course" WHERE "id" = %s', (course_id,)
        )
        course_result = cursor.fetchone()
        course_name = course_result["name"] if course_result else course_id
        course_code = course_result["code"] if course_result else ""

        cursor.execute('SELECT "name" FROM "Class" WHERE "id" = %s', (class_id,))
        class_result = cursor.fetchone()
        class_name = class_result["name"] if class_result else class_id
    logger.debug("Course and class names fetched from database.")

    # Create Excel writer
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        # Write student data to sheet, starting from row 12 to leave space for headers
        df.to_excel(writer, sheet_name="Student Scores", index=False, startrow=11)
        logger.debug("Student data written to Excel sheet.")

        # Get the worksheet to apply formatting
        workbook = writer.book
        worksheet = workbook["Student Scores"]

        # Add title and summary information
        from openpyxl.styles import Font, Border, PatternFill, Alignment

        # Title row: merged cells A1 to H1 for a prominent course title
        worksheet.merge_cells("A1:H1")
        worksheet["A1"] = f"{course_code} - {course_name}"
        worksheet["A1"].font = Font(size=22, bold=True)
        worksheet["A1"].alignment = Alignment(horizontal="center", vertical="center")
        worksheet["A1"].fill = PatternFill(
            start_color="D9E1F2", end_color="D9E1F2", fill_type="solid"
        )
        logger.debug("Title row formatted.")

        # Summary section starting at row 2 with clear labels and values
        summary_data = [
            ("Course Code:", course_code),
            ("Course Name:", course_name),
            ("Class Name:", class_name),
            ("Total Students:", student_count),
            ("Total Quizzes:", quiz_count),
            ("Generated On:", datetime.now().strftime("%d/%m/%Y %H:%M:%S")),
            ("CourseId:", course_id),
            ("ClassId:", class_id),
        ]
        for i, (label, value) in enumerate(summary_data, start=2):
            label_cell = worksheet[f"A{i}"]
            label_cell.value = label
            label_cell.font = Font(bold=True)
            worksheet[f"B{i}"] = value
        logger.debug("Summary data added to Excel sheet.")

        # Student data headers (and data) will start from row 12, as defined in df.to_excel

        # Make the main headers bold (row 12)
        for cell in worksheet[12]:  # Row 12 has the student headers
            cell.border = Border()  # Remove border for dumped cells
            if cell.value not in ["Student Name", "Roll Number"]:
                # Empty cell for quiz title
                cell.value = ""
            else:
                cell.font = Font(bold=True)
        logger.debug("Student data headers formatted.")

        # Quiz details header section starting at row 8, leaving ample space for the summary above
        quiz_titles = list(quiz_details.keys())
        start_col = 3  # starting from column C
        # Place Quiz Titles in row 10 with contrasting style and wrap text enabled
        for idx, title in enumerate(quiz_titles, start=start_col):
            col_letter = get_column_letter(idx)
            cell = worksheet[f"{col_letter}10"]
            cell.value = title
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill(
                start_color="4F81BD", end_color="4F81BD", fill_type="solid"
            )
            # Enable text wrapping to handle long quiz titles
            cell.alignment = Alignment(
                wrap_text=True, horizontal="center", vertical="center"
            )
        logger.debug("Quiz titles added to Excel sheet.")

        # Place Quiz Dates in row 11
        for idx, title in enumerate(quiz_titles, start=start_col):
            col_letter = get_column_letter(idx)
            worksheet[f"{col_letter}11"] = quiz_details[title]["date"]
            worksheet[f"{col_letter}11"].font = Font(bold=True)
            worksheet[f"{col_letter}11"].fill = PatternFill(
                start_color="FFD966", end_color="FFD966", fill_type="solid"
            )
        logger.debug("Quiz dates added to Excel sheet.")

        # Place Quiz Total Scores in row 12
        for idx, title in enumerate(quiz_titles, start=start_col):
            col_letter = get_column_letter(idx)
            worksheet[f"{col_letter}12"] = f"Total: {quiz_details[title]['totalScore']}"
            worksheet[f"{col_letter}12"].font = Font(bold=True)
            worksheet[f"{col_letter}12"].fill = PatternFill(
                start_color="FFD966", end_color="FFD966", fill_type="solid"
            )
            worksheet[f"{col_letter}12"].alignment = Alignment(horizontal="left")
        logger.debug("Quiz total scores added to Excel sheet.")

        # Auto-adjust column width
        for col in worksheet.columns:
            max_length = 0
            column = (
                col[0].column if hasattr(col[0], "column") else col[0].column_letter
            )
            column_letter = (
                get_column_letter(column) if isinstance(column, int) else column
            )
            for cell in col:
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))
            adjusted_width = max_length + 2
            worksheet.column_dimensions[column_letter].width = adjusted_width
        logger.debug("Column widths auto-adjusted.")

    # Reset file pointer to beginning
    output.seek(0)
    logger.debug("File pointer reset to beginning.")

    # Save the Excel file to a BytesIO object
    if save_to_file:
        await save_excel_report(output, course_id)
    return output


def get_column_letter(col_idx):
    """Convert column index to Excel column letter (1-based)"""
    from openpyxl.utils import get_column_letter as openpyxl_get_column_letter

    return openpyxl_get_column_letter(col_idx)


async def save_excel_report(
    excel_data: BytesIO, course_id: str, directory: str = "data/reports"
):
    """
    Save the Excel report (BytesIO object) to a file and return the file path.
    """
    logger.debug(
        f"Saving Excel report for course ID: {course_id} to directory: {directory}"
    )
    # Create directory if it doesn't exist
    os.makedirs(directory, exist_ok=True)
    logger.debug(f"Directory '{directory}' created (if not exists).")

    # Create filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{directory}/course_{course_id}_report_{timestamp}.xlsx"
    logger.debug(f"Filename generated: {filename}")

    # Save to file
    with open(filename, "wb") as file:
        file.write(excel_data.getvalue())

    logger.debug(f"Excel report saved to {filename}")
    return filename


if __name__ == "__main__":
    # Example usage
    import asyncio

    # Test fetch_course_report
    course_id = "2267b112a08249659ca72519f78ca56d"
    report = asyncio.run(fetch_course_report(course_id))
    # print(report)
    with open("data/course_report.json", "w") as f:
        import json
        from app.utils.misc import DateTimeEncoder

        json.dump(report, f, indent=4, cls=DateTimeEncoder)

    # Test save_excel_report
    directory = "data/reports"
    filename = asyncio.run(generate_excel_report(course_id, save_to_file=True))
