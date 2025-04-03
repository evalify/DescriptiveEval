from pydantic import BaseModel
from typing import Optional


class CourseReportRequest(BaseModel):
    course_id: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class ClassReportRequest(BaseModel):
    class_id: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
