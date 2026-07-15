from bson import ObjectId
from app.db.mongodb import get_db
from app.models.document import DocumentModel

class DocumentRepository:

    def get_collection(self):
        db = get_db()
        return db[DocumentModel.collection_name]

    async def create(self, document: DocumentModel) -> str:
        collection = self.get_collection()
        result = await collection.insert_one(document.to_dict())
        return str(result.inserted_id)

    async def find_by_project_id(self, project_id: str) -> list:
        collection = self.get_collection()
        cursor = collection.find({"project_id": project_id})
        documents = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            documents.append(doc)
        return documents

    async def find_by_id(self, document_id: str) -> dict | None:
        collection = self.get_collection()
        doc = await collection.find_one({"_id": ObjectId(document_id)})
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc

    async def delete_by_id(self, document_id: str) -> bool:
        collection = self.get_collection()
        result = await collection.delete_one({"_id": ObjectId(document_id)})
        return result.deleted_count > 0

    async def update_status(self, document_id: str, status: str) -> None:
        collection = self.get_collection()
        await collection.update_one({"_id": ObjectId(document_id)}, {"$set": {"status": status}})

    async def update_fields(self, document_id: str, fields: dict) -> None:
        collection = self.get_collection()
        await collection.update_one({"_id": ObjectId(document_id)}, {"$set": fields})