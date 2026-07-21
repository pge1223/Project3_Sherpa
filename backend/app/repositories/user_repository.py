from datetime import datetime
from typing import Optional
from app.db.mongodb import get_db
from app.models.user import UserModel


class UserRepository:

    def get_collection(self):
        db = get_db()
        return db[UserModel.collection_name]

    async def find_by_email(self, email: str) -> Optional[dict]:
        collection = self.get_collection()
        return await collection.find_one({"email": email})

    async def create_user(self, user_data: dict) -> dict:
        collection = self.get_collection()
        result = await collection.insert_one(user_data)
        user_data["_id"] = result.inserted_id
        return user_data

    async def upsert_profile(self, email: str, profile_data: dict) -> dict:
        collection = self.get_collection()
        now = datetime.utcnow()
        await collection.update_one(
            {"email": email},
            {
                "$set": {"profile": profile_data, "updated_at": now},
                "$setOnInsert": {"email": email, "created_at": now},
            },
            upsert=True,
        )
        return await collection.find_one({"email": email})