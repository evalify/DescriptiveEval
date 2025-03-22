from pydantic import BaseModel


class CourseReportRequest(BaseModel):
    course_id: str


class ClassReportRequest(BaseModel):
    class_id: str
