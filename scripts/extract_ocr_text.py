"""
contest_works의 ocr_text 필드 채우기 — POST(epilogueNewView.do)로 받은
textarea(#wrkCn{wrk_id}) HTML에서 순수 텍스트만 추출해 저장.

주의: 실제 이미지 OCR이 아니라 "HTML에 이미 텍스트로 들어있는 내용"만
추출한다. images가 있는 작품(포스터/PPT 스캔)은 텍스트가 이미지 안에
박혀 있어서 이 스크립트로는 빈 문자열("")이 저장된다 — 진짜 OCR은 별도
작업으로 남겨둔다.

- ocr_text: None  → 아직 처리 안 함
- ocr_text: ""    → 처리했지만 추출된 텍스트 없음 (이미지/영상 전용 등)
- ocr_text: "..." → 추출된 텍스트

실행:
  python scripts/extract_ocr_text.py            # 테스트 5건만
  python scripts/extract_ocr_text.py --limit 20  # 20건
  python scripts/extract_ocr_text.py --all       # 전체(ocr_text=None) 처리
"""

import argparse
import random
import re
import sys
import time
from html import unescape

import requests
from bs4 import BeautifulSoup
from pymongo import MongoClient

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MONGO_URI = "mongodb://reviewboard_admin:reviewboard2026!@127.0.0.1:27017/?authSource=admin"

LIST_URL = "https://sotong.go.kr/front/epilogue/epilogueNewList.do"
VIEW_URL = "https://sotong.go.kr/front/epilogue/epilogueNewView.do"
LIST_PAGE_URL = "https://sotong.go.kr/front/epilogue/epilogueNewListPage.do"

PAGETYPE_BY_STATUS = {"winner": "rslt", "candidate": "cnddt"}

MAX_RETRIES = 3
RETRYABLE_STATUS = (429, 503)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": f"{LIST_PAGE_URL}?pagetype=bbs&menu_id=527",
    "Origin": "https://sotong.go.kr",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
})


def get_csrf():
    r = session.get(f"{LIST_PAGE_URL}?pagetype=bbs&menu_id=527")
    soup = BeautifulSoup(r.text, "html.parser")
    meta = soup.find("meta", {"name": "_csrf"})
    return meta["content"] if meta else ""


def fetch_detail_html(bbs_id, pagetype, csrf):
    data = {
        "bbs_id": bbs_id,
        "new_bbs_id": "",
        "pagetype": pagetype,
        "progress": "6",
        "prevew_value": "",
        "_csrf": csrf,
    }
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.post(VIEW_URL, data=data, timeout=10)
        except requests.RequestException as e:
            if attempt == MAX_RETRIES:
                raise
            wait = 2 ** attempt
            print(f"    [RETRY {attempt}/{MAX_RETRIES}] 요청 실패({e}) — {wait}s 후 재시도")
            time.sleep(wait)
            continue

        if r.status_code in RETRYABLE_STATUS:
            if attempt == MAX_RETRIES:
                r.raise_for_status()
            wait = 2 ** attempt
            print(f"    [RETRY {attempt}/{MAX_RETRIES}] HTTP {r.status_code} — {wait}s 후 재시도")
            time.sleep(wait)
            continue

        r.raise_for_status()
        return r.text


def extract_text(detail_html, wrk_id):
    soup = BeautifulSoup(detail_html, "html.parser")
    textarea = soup.select_one(f"#wrkCn{wrk_id}")
    if not textarea:
        return None
    inner_html = unescape(textarea.string or "")
    inner_soup = BeautifulSoup(inner_html, "html.parser")
    text = inner_soup.get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5, help="처리할 문서 수 (기본 5, 테스트용)")
    parser.add_argument("--all", action="store_true", help="ocr_text=None 전체 처리 (--limit 무시)")
    args = parser.parse_args()

    client = MongoClient(MONGO_URI)
    col = client["ai_review_board"]["contest_works"]

    query = {"ocr_text": None, "bbs_id": {"$exists": True, "$ne": ""}}
    cursor = col.find(query, {"wrk_id": 1, "bbs_id": 1, "selection_status": 1, "work_title": 1})
    if not args.all:
        cursor = cursor.limit(args.limit)
    targets = list(cursor)

    print(f"처리 대상: {len(targets)}건 ({'전체' if args.all else f'--limit {args.limit}'})")
    if not targets:
        client.close()
        return

    csrf = get_csrf()
    cache = {}
    updated = skipped = 0

    for doc in targets:
        wrk_id = doc.get("wrk_id")
        bbs_id = doc.get("bbs_id")
        pagetype = PAGETYPE_BY_STATUS.get(doc.get("selection_status"))
        if not wrk_id or not bbs_id or not pagetype:
            print(f"  [SKIP] {doc.get('_id')} — wrk_id/bbs_id/selection_status 누락")
            skipped += 1
            continue

        cache_key = (bbs_id, pagetype)
        if cache_key not in cache:
            try:
                cache[cache_key] = fetch_detail_html(bbs_id, pagetype, csrf)
            except Exception as e:
                print(f"  [ERROR] bbs_id={bbs_id} 상세 조회 실패: {e}")
                skipped += 1
                continue
            time.sleep(random.uniform(0.3, 0.8))

        text = extract_text(cache[cache_key], wrk_id)
        if text is None:
            print(f"  [NOT FOUND] wrk_id={wrk_id} — textarea 없음")
            skipped += 1
            continue

        col.update_one({"_id": doc["_id"]}, {"$set": {"ocr_text": text}})
        updated += 1
        preview = text[:60] if text else "(빈 텍스트)"
        print(f"  [OK] {doc.get('work_title', '')[:25]:25s} | len={len(text):4d} | {preview}")

    print(f"\n완료: 업데이트 {updated}건 / 스킵 {skipped}건")
    client.close()


if __name__ == "__main__":
    main()
