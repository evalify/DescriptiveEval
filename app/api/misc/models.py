from pydantic import BaseModel
from typing import Optional, List


class CourseReportRequest(BaseModel):
    course_id: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    exclude_dates: bool = False  # Default is to include dates in the range
    specific_dates: Optional[List[str]] = (
        None  # List of specific dates to include/exclude
    )


class ClassReportRequest(BaseModel):
    class_id: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    exclude_dates: bool = False  # Default is to include dates in the range
    specific_dates: Optional[List[str]] = (
        None  # List of specific dates to include/exclude
    )
