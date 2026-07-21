"""
기존 contest_works 컬렉션(954건)에 source_url 필드 채우기.

배경: 소통혁신24는 작품(wrk_id) 단위 개별 페이지가 없고, 공모전(bbs_id)
상세 페이지 안에서 JS 팝업(viewCnddtWrkCn)으로만 작품 내용을 보여준다.
따라서 같은 bbs_id + selection_status를 가진 작품들은 동일한 source_url을
공유하며, 이 URL은 해당 공모전의 수상작/후보작 상세 페이지를 가리킨다.

실행: python scripts/update_source_url.py
"""

from pymongo import MongoClient
from pymongo import UpdateOne

MONGO_URI = "mongodb://reviewboard_admin:reviewboard2026!@127.0.0.1:27017/?authSource=admin"

VIEW_PAGE_URL = "https://sotong.go.kr/front/epilogue/epilogueNewViewPage.do"

# selection_status별 실제 브라우저 접근용 상세 페이지 menu_id
# (list 페이지 menu_id와는 다름 — winner=527, candidate=528이지만
#  상세 페이지는 winner=529, candidate=528로 확인됨)
SOURCE_PAGE_INFO = {
    "winner": {"pagetype": "rslt", "menu_id": 529},
    "candidate": {"pagetype": "cnddt", "menu_id": 528},
}


def build_source_url(bbs_id, selection_status):
    info = SOURCE_PAGE_INFO.get(selection_status, SOURCE_PAGE_INFO["winner"])
    return f"{VIEW_PAGE_URL}?menu_id={info['menu_id']}&bbs_id={bbs_id}&pagetype={info['pagetype']}"


def main():
    client = MongoClient(MONGO_URI)
    col = client["ai_review_board"]["contest_works"]

    targets = list(col.find(
        {"bbs_id": {"$exists": True, "$ne": ""}},
        {"_id": 1, "bbs_id": 1, "selection_status": 1},
    ))
    print(f"대상 문서: {len(targets)}건")

    ops = []
    skipped = 0
    for doc in targets:
        bbs_id = doc.get("bbs_id")
        selection_status = doc.get("selection_status")
        if not bbs_id or selection_status not in SOURCE_PAGE_INFO:
            skipped += 1
            continue
        url = build_source_url(bbs_id, selection_status)
        ops.append(UpdateOne({"_id": doc["_id"]}, {"$set": {"source_url": url}}))

    if ops:
        result = col.bulk_write(ops)
        print(f"업데이트 완료: {result.modified_count}건")
    else:
        print("업데이트할 문서 없음")

    if skipped:
        print(f"스킵됨(bbs_id/selection_status 없음): {skipped}건")

    remaining = col.count_documents({"source_url": None})
    print(f"source_url 남아있는 None: {remaining}건")

    client.close()


if __name__ == "__main__":
    main()
