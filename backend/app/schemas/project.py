from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class ProjectCreateRequest(BaseModel):
    title: str
    doc_type: str
    description: Optional[str] = None

class ProjectUpdateRequest(BaseModel):
    title: Optional[str] = None
    doc_type: Optional[str] = None
    description: Optional[str] = None
    domain: Optional[str] = None

class ProjectResponse(BaseModel):
    id: str
    user_email: str
    title: str
    doc_type: str
    description: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime