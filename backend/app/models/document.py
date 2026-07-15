from datetime import datetime
from typing import Optional
from bson import ObjectId

class DocumentModel:
    collection_name = "documents"

    def __init__(
        self,
        project_id: str,
        user_email: str,
        original_filename: str,
        stored_filename: str,
        file_path: str,
        file_size: int,
        mime_type: str,
        status: str = "uploaded",
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        source_type: str = "pdf",
        _id: Optional[ObjectId] = None,
        
    ):
        self._id = _id
        self.project_id = project_id
        self.user_email = user_email
        self.original_filename = original_filename
        self.stored_filename = stored_filename
        self.file_path = file_path
        self.file_size = file_size
        self.mime_type = mime_type
        self.status = status
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()
        self.source_type = source_type

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "user_email": self.user_email,
            "original_filename": self.original_filename,
            "stored_filename": self.stored_filename,
            "file_path": self.file_path,
            "file_size": self.file_size,
            "mime_type": self.mime_type,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source_type": self.source_type,
        }