"""
contest_works 컬렉션의 category / source_org 필드를 자동 채운다.

- source_org: contest_title 맨 앞 【기관명】 패턴을 정규식으로 추출
- category: contest_title을 gpt-4o-mini에 넣어 8개 카테고리 중 하나로 분류

같은 contest_title을 가진 work가 다수 존재하므로(공모전 1건 = work 여러 건),
분류는 "고유 contest_title" 단위로 배치 처리한다(10개씩) — 954건 전체를 개별
호출하는 대신 실제 LLM 호출 수를 줄이고, 분류 결과는 해당 title을 가진
모든 문서에 한 번에 반영한다. category가 이미 채워진 문서/타이틀은 건너뛴다
(재실행 시 이어서 처리 가능).

실행 전: 레포 루트 .env 또는 backend/.env에 OPENAI_API_KEY가 채워져 있어야 한다.
    python scripts/classify_contest_works.py            # 전체 실행
    python scripts/classify_contest_works.py --dry-run --limit 10   # DB에 쓰지 않고 결과만 확인
"""
import argparse
import json
import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from pymongo import MongoClient

load_dotenv()  # 레포 루트 .env (있으면)
load_dotenv(Path(__file__).resolve().parent.parent / "backend" / ".env")  # backend/.env 폴백

MONGO_URI = "mongodb://reviewboard_admin:reviewboard2026!@127.0.0.1:27017/?authSource=admin"
DB_NAME = "ai_review_board"
COLLECTION_NAME = "contest_works"

MODEL = "gpt-4o-mini"
BATCH_SIZE = 10

CATEGORIES = [
    "AI/데이터", "공공서비스", "환경/기후", "교육/연구",
    "복지/사회", "안전/재난", "창업/경제", "기타",
]

SOURCE_ORG_PATTERN = re.compile(r"^【([^】]+)】")


def extract_source_org(contest_title: str) -> str | None:
    match = SOURCE_ORG_PATTERN.match(contest_title)
    return match.group(1).strip() if match else None


def classify_titles(client: OpenAI, titles: list[str]) -> dict[str, str]:
    """titles(최대 10개)를 한 번의 LLM 호출로 분류해 {title: category}를 반환한다."""
    numbered = "\n".join(f"{i + 1}. {title}" for i, title in enumerate(titles))
    prompt = (
        "다음은 공모전/경진대회 제목 목록이다. 각 제목을 아래 카테고리 중 "
        "정확히 하나로 분류하라.\n\n"
        f"카테고리 목록: {', '.join(CATEGORIES)}\n\n"
        f"제목 목록:\n{numbered}\n\n"
        '반드시 JSON 객체로만 답하라. 키는 번호(문자열), 값은 카테고리 이름이다. '
        '예: {"1": "AI/데이터", "2": "기타"}'
    )

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        response_format={"type": "json_object"},
    )
    parsed = json.loads(response.choices[0].message.content)

    result = {}
    for i, title in enumerate(titles):
        category = parsed.get(str(i + 1))
        if category not in CATEGORIES:
            print(f"    [경고] 분류 결과 이상 → '기타'로 대체: {title[:40]} (응답: {category!r})")
            category = "기타"
        result[title] = category
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                         help="DB에 쓰지 않고 분류 결과만 출력")
    parser.add_argument("--limit", type=int, default=None,
                         help="처리할 고유 contest_title 개수 제한(테스트용)")
    args = parser.parse_args()

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY가 설정되어 있지 않다. 레포 루트 .env 또는 backend/.env를 확인할 것.")

    client = OpenAI(api_key=api_key)
    mongo = MongoClient(MONGO_URI)
    col = mongo[DB_NAME][COLLECTION_NAME]

    titles = col.distinct("contest_title", {"category": None})
    if args.limit is not None:
        titles = titles[:args.limit]

    mode = "[DRY-RUN] " if args.dry_run else ""
    print(f"{mode}분류 대상 고유 contest_title: {len(titles)}건 "
          f"(전체 미분류 문서: {col.count_documents({'category': None})}건)")

    updated_docs = 0
    for batch_start in range(0, len(titles), BATCH_SIZE):
        batch = titles[batch_start:batch_start + BATCH_SIZE]
        batch_no = batch_start // BATCH_SIZE + 1
        print(f"\n[배치 {batch_no}] {len(batch)}개 title 처리 중...")

        try:
            categorized = classify_titles(client, batch)
        except Exception as e:
            print(f"  [오류] LLM 호출 실패, 이 배치 스킵 (다음 실행 시 재시도됨): {e}")
            continue

        for title in batch:
            source_org = extract_source_org(title)
            category = categorized[title]
            match_count = col.count_documents({"contest_title": title, "category": None})

            if args.dry_run:
                print(f"  [{category}] source_org={source_org!r} | {title[:40]} "
                      f"→ (dry-run) 대상 {match_count}건, 실제 갱신 안 함")
                continue

            res = col.update_many(
                {"contest_title": title, "category": None},
                {"$set": {"source_org": source_org, "category": category}},
            )
            updated_docs += res.modified_count
            print(f"  [{category}] source_org={source_org!r} | {title[:40]} "
                  f"→ {res.modified_count}건 갱신")

        time.sleep(0.5)

    if args.dry_run:
        print("\nDRY-RUN 완료 — DB에는 아무 것도 반영되지 않았다.")
    else:
        print(f"\n완료! 문서 {updated_docs}건 업데이트 "
              f"(남은 미분류 문서: {col.count_documents({'category': None})}건)")
    mongo.close()


if __name__ == "__main__":
    main()
