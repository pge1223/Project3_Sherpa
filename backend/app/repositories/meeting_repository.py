# 작성자: 가은/Claude (2026-07-15, MTG-005 — 윤한 합의)
# document_repository.py와 동일한 패턴(get_db() -> collection, _id는 저장 밖에선 항상 str).
from datetime import datetime

from bson import ObjectId

from app.db.mongodb import get_db
from app.models.meeting import MeetingModel


class MeetingRepository:

    def get_collection(self):
        db = get_db()
        return db[MeetingModel.collection_name]

    async def create(self, meeting: MeetingModel) -> str:
        collection = self.get_collection()
        result = await collection.insert_one(meeting.to_dict())
        return str(result.inserted_id)

    async def find_latest_by_project_id(self, project_id: str) -> dict | None:
        """MTG-007 재평가는 프로젝트의 가장 최근 회의 결과를 이전 회의로 취급한다."""
        collection = self.get_collection()
        doc = await collection.find_one({"project_id": project_id}, sort=[("created_at", -1)])
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc

    async def find_by_project_id(self, project_id: str) -> list:
        collection = self.get_collection()
        cursor = collection.find({"project_id": project_id}).sort("created_at", -1)
        meetings = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            meetings.append(doc)
        return meetings

    async def update_result_by_id(self, meeting_doc_id: str, patch: dict) -> None:
        collection = self.get_collection()
        await collection.update_one(
            {"_id": ObjectId(meeting_doc_id)},
            {"$set": {**patch, "updated_at": datetime.utcnow()}},
        )
