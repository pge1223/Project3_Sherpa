import os

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import PyMongoError


load_dotenv()

mongodb_url = os.getenv("MONGODB_URL")
db_name = os.getenv("MONGODB_DB")


def main() -> None:
    if not mongodb_url or not db_name:
        print("❌ .env에 MONGODB_URL과 MONGODB_DB를 설정해주세요.")
        return

    client: MongoClient | None = None

    try:
        client = MongoClient(
            mongodb_url,
            directConnection=True,
            serverSelectionTimeoutMS=5000,
        )

        client.admin.command("ping")
        print("✅ MongoDB 연결 및 인증 성공")

        db = client[db_name]
        print("DB:", db_name)
        print("컬렉션:", db.list_collection_names())

    except PyMongoError as error:
        print("❌ MongoDB 오류:", error)

    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    main()
