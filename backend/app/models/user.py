from datetime import datetime
from typing import Optional
from bson import ObjectId


class UserModel:
    collection_name = "users"

    def __init__(
        self,
        email: str,
        password: str,
        name: str,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        is_active: bool = True,
        _id: Optional[ObjectId] = None,
    ):
        self._id = _id
        self.email = email
        self.password = password
        self.name = name
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()
        self.is_active = is_active

    def to_dict(self) -> dict:
        return {
            "email": self.email,
            "password": self.password,
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "is_active": self.is_active,
        }