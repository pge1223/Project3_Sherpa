"""
소통혁신24 수상작(rslt) / 수상후보작(cnddt) 크롤링
저장: MongoDB ai_review_board.contest_works
고유키: wrk_id
"""

import re
import time
import requests
from bs4 import BeautifulSoup
from pymongo import MongoClient
from datetime import datetime
from html import unescape

# ── MongoDB ───────────────────────────────────────────────
MONGO_URI = "mongodb://reviewboard_admin:reviewboard2026!@127.0.0.1:27017/ai_review_board?authSource=admin"
client = MongoClient(MONGO_URI)
col = client["ai_review_board"]["contest_works"]
col.create_index("wrk_id", unique=True)  # 중복 방지
IT_KEYWORDS = [
    "IT", "SW", "소프트웨어", "AI", "인공지능", "데이터", "빅데이터",
    "디지털", "앱", "플랫폼", "해커톤", "클라우드", "개발", "스타트업", "창업", "정보"
]

def is_it_related(title):
    return any(kw.lower() in title.lower() for kw in IT_KEYWORDS)

BASE_URL = "https://sotong.go.kr"
LIST_URL = "https://sotong.go.kr/front/epilogue/epilogueNewList.do"
VIEW_URL = "https://sotong.go.kr/front/epilogue/epilogueNewView.do"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://sotong.go.kr/front/epilogue/epilogueNewListPage.do?pagetype=bbs&menu_id=527",
    "Origin": "https://sotong.go.kr",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
})

# ── CSRF 토큰 ─────────────────────────────────────────────
def get_csrf(pagetype="bbs", menu_id=527):
    url = f"https://sotong.go.kr/front/epilogue/epilogueNewListPage.do?pagetype={pagetype}&menu_id={menu_id}"
    r = session.get(url)
    soup = BeautifulSoup(r.text, "html.parser")
    meta = soup.find("meta", {"name": "_csrf"})
    return meta["content"] if meta else ""

# ── 목록 페이지 (수상작/후보작) ───────────────────────────
def fetch_list_page(page, pagetype, menu_id, csrf):
    data = {
        "miv_pageNo": page,
        "miv_pageSize": "",
        "orderBy": "",
        "bbs_id": "",
        "pagetype": pagetype,
        "epilogue_bgnde": "",
        "epilogue_endde": "",
        "date_range": "all",
        "epilogue_bgnde_cnddt": "",
        "epilogue_endde_cnddt": "",
        "date_range_cnddt": "all",
        "search_insttNm": "",
        "search_title_contents": "",
        "search_wrk_sj": "",
        "search_result": "",
        "search_result_cnddt": "",
        "_csrf": csrf,
    }
    r = session.post(LIST_URL, data=data, timeout=10)
    return r.text

def parse_list(html):
    """목록에서 공모전 기본 정보 추출"""
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for li in soup.select("li.contest-wrap"):
        a = li.select_one("a.contest-con")
        if not a:
            continue
        title_el = li.select_one(".title")
        title = title_el.get_text(strip=True) if title_el else ""
        href = BASE_URL + a["href"] if a.get("href") else ""
        inst_el = li.select_one(".info p")
        inst_nm = inst_el.get_text(strip=True) if inst_el else ""
        bbs_match = re.search(r'bbs_id=([a-zA-Z0-9]+)', href)
        bbs_id = bbs_match.group(1) if bbs_match else ""
        if not bbs_id:
            continue
        items.append({"bbs_id": bbs_id, "contest_title": title, "inst_nm": inst_nm, "href": href})
    return items

# ── 상세 페이지 (작품 목록 + 이미지 URL) ─────────────────
def fetch_detail(bbs_id, pagetype, csrf):
    data = {
        "bbs_id": bbs_id,
        "new_bbs_id": "",
        "pagetype": pagetype,
        "progress": "6",
        "prevew_value": "",
        "_csrf": csrf,
    }
    r = session.post(VIEW_URL, data=data, timeout=10)
    return r.text

def parse_works(html, bbs_id, contest_title, inst_nm, selection_status):
    soup = BeautifulSoup(html, "html.parser")
    works = []

    # 수상작(rslt): a.view_wrap / 수상후보작(cnddt): a.result_view
    selector = "a.view_wrap" if selection_status == "winner" else "a.result_view"

    for a in soup.select(selector):
        href = a.get("href", "")
        wrk_match = re.search(r"viewCnddtWrkCn\('([a-zA-Z0-9]+)'\)", href)
        if not wrk_match:
            continue
        wrk_id = wrk_match.group(1)

        title_el = a.select_one(f"#wrkCn_title_{wrk_id}")
        work_title = title_el.get_text(strip=True) if title_el else a.get("title", "")

        grade_el = a.select_one(".tape_type span")
        award_grade = grade_el.get_text(strip=True) if grade_el else ""

        textarea = a.select_one(f"#wrkCn{wrk_id}")
        images = []
        if textarea:
            inner_html = unescape(textarea.string or "")
            inner_soup = BeautifulSoup(inner_html, "html.parser")
            for order, img in enumerate(inner_soup.find_all("img"), start=1):
                src = img.get("src", "")
                if src:
                    full_url = BASE_URL + src if src.startswith("/") else src
                    images.append({"order": order, "url": full_url})

        works.append({
            "wrk_id": wrk_id,
            "bbs_id": bbs_id,
            "contest_title": contest_title,
            "inst_nm": inst_nm,
            "work_title": work_title,
            "award_grade": award_grade,
            "selection_status": selection_status,
            "category": None,
            "images": images,
            "ocr_text": None,
            "crawled_at": datetime.utcnow(),
        })

    return works

# ── 메인 ─────────────────────────────────────────────────
def crawl(pagetype, selection_status, menu_id, label, max_pages=300):
    print(f"\n{'='*50}")
    print(f"{label} 크롤링 시작 (pagetype={pagetype})")
    print(f"{'='*50}")

    csrf = get_csrf(pagetype=pagetype, menu_id=menu_id)
    saved = skipped = total_contests = total_works = 0

    for page in range(1, max_pages + 1):
        print(f"\n[페이지 {page}]")
        try:
            html = fetch_list_page(page, pagetype, menu_id, csrf)
            items = parse_list(html)
        except Exception as e:
            print(f"  목록 오류: {e}")
            time.sleep(2)
            continue

        if not items:
            print("  항목 없음 → 종료")
            break

        total_contests += len(items)
        print(f"  공모전 {len(items)}건")

        for item in items:
            print(f"  → [{item['bbs_id'][:8]}] {item['contest_title'][:35]}")
            if not is_it_related(item["contest_title"]):
                print(f"  → [SKIP] {item['contest_title'][:35]}")
                continue
            try:
                detail_html = fetch_detail(item["bbs_id"], pagetype, csrf)
                works = parse_works(
                    detail_html,
                    item["bbs_id"],
                    item["contest_title"],
                    item["inst_nm"],
                    selection_status,
                )
            except Exception as e:
                print(f"     상세 오류: {e}")
                time.sleep(1)
                continue

            for work in works:
                try:
                    col.insert_one(work)
                    print(f"     [저장] {work['award_grade']} | {work['work_title'][:30]} | 이미지 {len(work['images'])}장")
                    saved += 1
                except Exception:
                    print(f"     [SKIP] {work['work_title'][:30]} (중복)")
                    skipped += 1

            total_works += len(works)
            time.sleep(0.5)

        time.sleep(0.5)

    print(f"\n완료! 공모전 {total_contests}건 | 작품 저장 {saved}건 | 중복 스킵 {skipped}건")
    return saved

def main():
    # 수상작
    crawl(
        pagetype="rslt",
        selection_status="winner",
        menu_id=527,
        label="수상작",
    )

    # 수상후보작
    crawl(
        pagetype="cnddt",
        selection_status="candidate",
        menu_id=528,
        label="수상후보작",
    )

    total = col.count_documents({})
    print(f"\n전체 contest_works 컬렉션: {total}건")
    client.close()

if __name__ == "__main__":
    main()
