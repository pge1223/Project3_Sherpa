import os


from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import PyMongoError


load_dotenv()


host = os.getenv("MONGO_HOST")
port = os.getenv("MONGO_PORT")
user = os.getenv("MONGO_USER")
password = os.getenv("MONGO_PASSWORD")
auth_source = os.getenv("MONGO_AUTH_SOURCE")
db_name = os.getenv("MONGO_DB")


# 비밀번호 내용은 출력하지 않고 로드 여부만 확인
print("HOST:", host)
print("PORT:", port)
print("USER:", user)
print("PASSWORD 로드 여부:", bool(password))
print("AUTH SOURCE:", auth_source)
print("DB:", db_name)


try:
    client = MongoClient(
        f"mongodb://{host}:{port}",
        username=user,
        password=password,
        authSource=auth_source,
        directConnection=True,
        serverSelectionTimeoutMS=5000,
    )


    client.admin.command("ping")
    print("✅ MongoDB 연결 및 인증 성공")


    db = client[db_name]


    print("컬렉션:", db.list_collection_names())
    print("K-Startup:", db["kstartup_raw"].count_documents({}))
    print("기업마당:", db["bizinfo_raw"].count_documents({}))


except PyMongoError as error:
    print("❌ MongoDB 오류:", error)


finally:
    try:
        client.close()
    except NameError:
        pass
