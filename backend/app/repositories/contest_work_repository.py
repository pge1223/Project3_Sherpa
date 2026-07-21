from app.db.mongodb import get_db


# 가은/Claude(2026-07-21): kyh님이 크롤링(crawl_sotong_winners.py)해서 채운 소통혁신24
# 수상작 아카이브 조회 전용 — 이 앱이 직접 쓰는 컬렉션이 아니라 읽기 전용으로만 접근한다.
# category/source_org는 scripts/classify_contest_works.py가 나중에 채워 넣는 필드라
# 아직 분류 안 된 문서는 category가 없을 수 있다(그런 문서는 자동으로 매칭에서 빠진다).
class ContestWorkRepository:
    COLLECTION_NAME = "contest_works"

    def get_collection(self):
        db = get_db()
        return db[self.COLLECTION_NAME]

    # 수상작(winner)을 후보작(candidate)보다 우선 채우고, 모자라면 후보작으로 나머지를 채운다.
    async def find_by_category(self, category: str, limit: int = 4) -> list[dict]:
        collection = self.get_collection()
        winners = await collection.find(
            {"category": category, "selection_status": "winner"}
        ).to_list(length=limit)
        remaining = limit - len(winners)
        candidates = []
        if remaining > 0:
            candidates = await collection.find(
                {"category": category, "selection_status": "candidate"}
            ).to_list(length=remaining)
        return winners + candidates
