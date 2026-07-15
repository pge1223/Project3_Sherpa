import re
from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings

client: AsyncIOMotorClient = None
db = None


def _masked_url(url: str) -> str:
    """비밀번호 부분을 ***로 마스킹해 로그에 출력"""
    return re.sub(r"(:)[^:@]+(@)", r"\1***\2", url)


async def connect_db():
    global client, db
    print(f"[MongoDB] 로드된 URL: {_masked_url(settings.MONGODB_URL)}")
    print(f"[MongoDB] 대상 DB: {settings.MONGODB_DB}")
    client = AsyncIOMotorClient(
        settings.MONGODB_URL,
        serverSelectionTimeoutMS=5000,  # 5초 내 연결 실패 시 즉시 에러
    )
    # motor는 lazy connect이므로 ping으로 실제 인증 여부를 즉시 확인
    await client.admin.command("ping")
    db = client[settings.MONGODB_DB]
    print(f"[MongoDB] 연결 및 인증 성공: {settings.MONGODB_DB}")


async def close_db():
    global client
    if client:
        client.close()
        print("MongoDB 연결 종료")


def get_db():
    return db