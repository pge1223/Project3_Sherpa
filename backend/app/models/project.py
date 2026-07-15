from datetime import datetime
from typing import Optional, List
from bson import ObjectId

class ProjectModel:
    collection_name = "projects"

    def __init__(
        self,
        user_email: str,
        title: str,
        doc_type: str,
        description: Optional[str] = None,
        status: str = "pending",
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        _id: Optional[ObjectId] = None,
    ):
        self._id = _id
        self.user_email = user_email
        self.title = title
        self.doc_type = doc_type
        self.description = description
        self.status = status
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()

    def to_dict(self) -> dict:
        return {
            "user_email": self.user_email,
            "title": self.title,
            "doc_type": self.doc_type,
            "description": self.description,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }