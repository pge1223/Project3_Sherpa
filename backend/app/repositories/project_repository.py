from datetime import datetime
from typing import Optional, List
from bson import ObjectId
from app.db.mongodb import get_db
from app.models.project import ProjectModel

class ProjectRepository:

    def get_collection(self):
        db = get_db()
        return db[ProjectModel.collection_name]

    async def create_project(self, project_data: dict) -> dict:
        collection = self.get_collection()
        result = await collection.insert_one(project_data)
        project_data["_id"] = result.inserted_id
        return project_data

    async def find_by_user(self, user_email: str) -> List[dict]:
        collection = self.get_collection()
        cursor = collection.find({"user_email": user_email}).sort("updated_at", -1)
        return await cursor.to_list(length=100)

    async def find_by_id(self, project_id: str) -> Optional[dict]:
        collection = self.get_collection()
        return await collection.find_one({"_id": ObjectId(project_id)})

    async def find_by_id_and_user(self, project_id: str, user_email: str) -> Optional[dict]:
        collection = self.get_collection()
        return await collection.find_one({
            "_id": ObjectId(project_id),
            "user_email": user_email
        })

    async def update_project(self, project_id: str, update_data: dict) -> Optional[dict]:
        collection = self.get_collection()
        update_data["updated_at"] = datetime.utcnow()
        await collection.update_one(
            {"_id": ObjectId(project_id)},
            {"$set": update_data}
        )
        return await self.find_by_id(project_id)

    async def delete_project(self, project_id: str) -> bool:
        collection = self.get_collection()
        result = await collection.delete_one({"_id": ObjectId(project_id)})
        return result.deleted_count > 0