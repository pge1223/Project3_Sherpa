"""
소통혁신24 공고문(bbs) 텍스트 수집
=================================
읽기: contest_works.bbs_id (distinct, 103건)
저장: contest_announcements_it (bbs_id unique)

공고문 상세 페이지는 브라우저에서 두 단계로 로드된다:
  1) epilogueNewViewPage.do (GET) — 페이지 뼈대 + CSRF 토큰
  2) epilogueNewView.do (POST, pagetype=bbs) — 실제 공고문 HTML 조각
     (제목/본문/첨부파일 다운로드 링크가 이 조각 안에 있음)

텍스트 추출 우선순위:
  1) 첨부파일 중 pdf/hwp/hwpx가 있으면 다운로드 후 파싱(ai.rag.parsers.unified_parser)
  2) 첨부파일이 없거나(또는 전부 이미지/zip 등) 본문(div.tab-txt)에 텍스트가 있으면 그대로 사용
  3) 본문도 비어 있으면(이미지만 있는 공고 등) announcement_text=""로 저장

실행 전: 로컬 MongoDB 터널이 localhost:27018로 열려 있어야 한다.
실행: python scripts/crawl_announcements.py
"""

import random
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from pymongo import MongoClient

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ai.rag.parsers.exceptions import ParserError  # noqa: E402
from ai.rag.parsers.unified_parser import extract_document  # noqa: E402

MONGO_URI = "mongodb://reviewboard_admin:reviewboard2026!@localhost:27018/ai_review_board?authSource=admin"
DB_NAME = "ai_review_board"
SOURCE_COLLECTION = "contest_works"
TARGET_COLLECTION = "contest_announcements_it"

VIEW_PAGE_URL = "https://sotong.go.kr/front/epilogue/epilogueNewViewPage.do"
VIEW_URL = "https://sotong.go.kr/front/epilogue/epilogueNewView.do"
DOWNLOAD_URL = "https://sotong.go.kr/commonfile/downloadEpilogueAtchmnfl.do"
MENU_ID = 529

# 텍스트 추출 가능한 첨부파일 확장자만 대상으로 한다 (jpg/png/zip 등은 스킵)
DOC_EXTENSIONS = ("pdf", "hwp", "hwpx")

# 첨부파일 링크 표시 텍스트 예: "2. 공모전 포스터.jpg(2119KB)" → 크기 표시 제거
_SIZE_SUFFIX_PATTERN = re.compile(r"\(\d+[KMG]?B\)\s*$")
_ATCHMNFL_ID_PATTERN = re.compile(r"atchmnfl_id=([a-zA-Z0-9]+)")

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
})


def build_source_url(bbs_id: str) -> str:
    return f"{VIEW_PAGE_URL}?menu_id={MENU_ID}&bbs_id={bbs_id}&pagetype=bbs"


def fetch_csrf(bbs_id: str) -> str:
    r = session.get(
        VIEW_PAGE_URL,
        params={"menu_id": MENU_ID, "bbs_id": bbs_id, "pagetype": "bbs"},
        timeout=15,
    )
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    meta = soup.find("meta", {"name": "_csrf"})
    return meta["content"] if meta else ""


def fetch_bbs_detail_html(bbs_id: str, csrf: str) -> str:
    """실제 공고문 조각(제목/본문/첨부파일)을 담은 HTML을 반환"""
    data = {
        "bbs_id": bbs_id,
        "new_bbs_id": "",
        "pagetype": "bbs",
        "progress": "6",
        "prevew_value": "",
        "_csrf": csrf,
    }
    r = session.post(VIEW_URL, data=data, timeout=15)
    r.raise_for_status()
    return r.text


def parse_attachments(soup: BeautifulSoup) -> list[dict]:
    """공고문 상세 HTML에서 첨부파일(파일명 + atchmnfl_id) 목록을 문서 순서대로 추출"""
    attachments = []
    for a in soup.select("div.award_download a[href*='downloadEpilogueAtchmnfl.do']"):
        m = _ATCHMNFL_ID_PATTERN.search(a.get("href", ""))
        if not m:
            continue
        raw_name = a.get_text(strip=True)
        filename = _SIZE_SUFFIX_PATTERN.sub("", raw_name).strip()
        ext = Path(filename).suffix.lower().lstrip(".")
        attachments.append({"atchmnfl_id": m.group(1), "filename": filename, "ext": ext})
    return attachments


def download_attachment(atchmnfl_id: str) -> bytes:
    r = session.get(DOWNLOAD_URL, params={"atchmnfl_id": atchmnfl_id}, timeout=30)
    r.raise_for_status()
    return r.content


def extract_attachment_text(content: bytes, ext: str) -> str:
    """다운로드한 첨부파일을 임시 파일로 저장해 파싱하고, 끝나면 임시 파일을 삭제"""
    tmp_path = Path(tempfile.gettempdir()) / f"sotong_atch_{time.time_ns()}.{ext}"
    tmp_path.write_bytes(content)
    try:
        result = extract_document(tmp_path)
        return "\n".join(block.content for block in result.blocks)
    finally:
        tmp_path.unlink(missing_ok=True)


def extract_body_text(soup: BeautifulSoup) -> str:
    tab_txt = soup.select_one("div.tab-txt")
    if not tab_txt:
        return ""
    return tab_txt.get_text("\n", strip=True)


def build_announcement(bbs_id: str, contest_title: str) -> dict:
    csrf = fetch_csrf(bbs_id)
    html = fetch_bbs_detail_html(bbs_id, csrf)
    soup = BeautifulSoup(html, "html.parser")

    doc_attachments = [a for a in parse_attachments(soup) if a["ext"] in DOC_EXTENSIONS]

    texts: list[str] = []
    file_type = "none"
    for att in doc_attachments:
        try:
            content = download_attachment(att["atchmnfl_id"])
            text = extract_attachment_text(content, att["ext"])
        except (requests.RequestException, ParserError, OSError) as e:
            print(f"    [경고] 첨부파일 처리 실패 ({att['filename']}): {e}")
            continue
        finally:
            time.sleep(random.uniform(1, 2))

        if text.strip():
            texts.append(text)
            if file_type == "none":
                file_type = att["ext"]  # 최초로 성공한 첨부파일의 확장자를 대표값으로 기록

    if texts:
        announcement_text = "\n\n".join(texts)
    else:
        body_text = extract_body_text(soup)
        if body_text:
            announcement_text = body_text
            file_type = "text"
        else:
            announcement_text = ""
            file_type = "none"

    return {
        "bbs_id": bbs_id,
        "contest_title": contest_title,
        "announcement_text": announcement_text,
        "source_url": build_source_url(bbs_id),
        "file_type": file_type,
        "created_at": datetime.now(timezone.utc),
    }


def main():
    mongo = MongoClient(MONGO_URI)
    db = mongo[DB_NAME]
    source_col = db[SOURCE_COLLECTION]
    target_col = db[TARGET_COLLECTION]
    target_col.create_index("bbs_id", unique=True)

    bbs_ids = source_col.distinct("bbs_id")
    print(f"대상 bbs_id: {len(bbs_ids)}건")

    saved = skipped = failed = 0
    for i, bbs_id in enumerate(bbs_ids, start=1):
        if target_col.find_one({"bbs_id": bbs_id}):
            print(f"[{i}/{len(bbs_ids)}] [SKIP] {bbs_id} (이미 저장됨)")
            skipped += 1
            continue

        work = source_col.find_one({"bbs_id": bbs_id}, {"contest_title": 1})
        contest_title = (work or {}).get("contest_title", "")

        print(f"[{i}/{len(bbs_ids)}] {bbs_id} | {contest_title[:40]}")
        try:
            doc = build_announcement(bbs_id, contest_title)
            target_col.insert_one(doc)
            print(f"    [저장] file_type={doc['file_type']} text_len={len(doc['announcement_text'])}")
            saved += 1
        except Exception as e:
            print(f"    [오류] {bbs_id} 처리 실패: {e}")
            failed += 1

        time.sleep(random.uniform(1, 2))

    print(f"\n완료! 저장 {saved}건 | 스킵 {skipped}건 | 실패 {failed}건")
    print(f"전체 {TARGET_COLLECTION} 컬렉션: {target_col.count_documents({})}건")
    mongo.close()


if __name__ == "__main__":
    main()
