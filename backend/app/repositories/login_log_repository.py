from datetime import datetime
from app.db.mongodb import get_db


# 가은/Claude(2026-07-21): "1번(실제 로그인)으로 하고 로그인 기록도 저장해줄 수 있나" —
# UserModel(users 컬렉션)과 별도로 로그인이 "언제, 몇 번" 있었는지 이력을 남긴다.
# users.last_login_at(최근 1회)만으로는 과거 로그인 이력이 덮어써져 사라지므로,
# 매 로그인마다 별도 로그 문서를 쌓는다.
class LoginLogRepository:
    collection_name = "login_logs"

    def get_collection(self):
        db = get_db()
        return db[self.collection_name]

    async def create_log(self, email: str) -> dict:
        collection = self.get_collection()
        log = {"email": email, "logged_in_at": datetime.utcnow()}
        result = await collection.insert_one(log)
        log["_id"] = result.inserted_id
        return log

    async def find_by_email(self, email: str, limit: int = 50) -> list:
        collection = self.get_collection()
        cursor = collection.find({"email": email}).sort("logged_in_at", -1).limit(limit)
        return await cursor.to_list(length=limit)
