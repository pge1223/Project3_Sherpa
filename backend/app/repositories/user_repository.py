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

    # 가은/Claude(2026-07-21): 로그인 기록 요청 — 매 로그인 이력은 LoginLogRepository가
    # 따로 쌓고, 여기서는 "가장 최근 로그인"만 사용자 문서에 바로 붙여둔다(목록에서
    # 빠르게 조회할 때 로그를 따로 join 안 해도 되도록).
    async def update_last_login(self, email: str) -> None:
        collection = self.get_collection()
        await collection.update_one({"email": email}, {"$set": {"last_login_at": datetime.utcnow()}})