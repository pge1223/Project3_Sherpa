"""
소통혁신24 IT 공모전 크롤링 (AJAX POST 방식)
저장: MongoDB ai_review_board.contest_announcements_it
"""

import time
import requests
from bs4 import BeautifulSoup
from pymongo import MongoClient
from datetime import datetime

MONGO_URI = "mongodb://reviewboard_admin:reviewboard2026!@127.0.0.1:27017/ai_review_board?authSource=admin"
client = MongoClient(MONGO_URI)
col = client["ai_review_board"]["contest_announcements_it"]

IT_KEYWORDS = [
    "IT", "SW", "소프트웨어", "AI", "인공지능", "데이터", "빅데이터",
    "디지털", "앱", "플랫폼", "해커톤", "클라우드", "개발", "스타트업", "창업", "정보"
]

AJAX_URL = "https://sotong.go.kr/front/epilogue/epilogueNewList.do"
BASE_URL = "https://sotong.go.kr"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://sotong.go.kr/front/epilogue/epilogueNewListPage.do?pagetype=bbs&menu_id=527",
    "Origin": "https://sotong.go.kr",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
})

def is_it_related(title):
    return any(kw.lower() in title.lower() for kw in IT_KEYWORDS)

def get_csrf():
    r = session.get("https://sotong.go.kr/front/epilogue/epilogueNewListPage.do?pagetype=bbs&menu_id=527")
    soup = BeautifulSoup(r.text, "html.parser")
    meta = soup.find("meta", {"name": "_csrf"})
    return meta["content"] if meta else ""

def fetch_page(page, csrf):
    data = {
        "miv_pageNo": page,
        "miv_pageSize": "",
        "orderBy": "",
        "bbs_id": "",
        "pagetype": "bbs",
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
    r = session.post(AJAX_URL, data=data, timeout=10)
    return r.text

def parse_items(html):
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for li in soup.select("li.contest-wrap"):
        a = li.select_one("a.contest-con")
        if not a:
            continue
        title_el = li.select_one(".title")
        title = title_el.get_text(strip=True) if title_el else ""
        href = BASE_URL + a["href"] if a.get("href") else ""
        date_el = li.select_one(".date")
        period = date_el.get_text(strip=True) if date_el else ""
        state_el = li.select_one(".state-area")
        status = state_el.get_text(strip=True) if state_el else ""
        inst_el = li.select_one(".info p")
        inst_nm = inst_el.get_text(strip=True) if inst_el else ""

        import re
        bbs_match = re.search(r'bbs_id=([a-zA-Z0-9]+)', href)
        bbs_id = bbs_match.group(1) if bbs_match else ""

        items.append({
            "title": title,
            "href": href,
            "bbs_id": bbs_id,
            "inst_nm": inst_nm,
            "period": period,
            "status": status,
        })
    return items

def main():
    print("=" * 50)
    print("소통혁신24 IT 공모전 크롤링 시작 (AJAX)")
    print("=" * 50)

    csrf = get_csrf()
    print(f"CSRF 토큰: {csrf[:20]}...")

    saved = skipped = total = 0
    MAX_PAGES = 241

    for page in range(1, MAX_PAGES + 1):
        print(f"\n[페이지 {page}/{MAX_PAGES}]")
        try:
            html = fetch_page(page, csrf)
            items = parse_items(html)
        except Exception as e:
            print(f"  오류: {e}")
            time.sleep(2)
            continue

        if not items:
            print("  항목 없음 → 종료")
            break

        total += len(items)
        it_items = [i for i in items if is_it_related(i["title"])]
        print(f"  전체 {len(items)}건 | IT 관련 {len(it_items)}건")

        for item in it_items:
            if col.find_one({"bbs_id": item["bbs_id"]}):
                print(f"    [SKIP] {item['title'][:40]}")
                skipped += 1
                continue
            print(f"    [저장] {item['title'][:40]}")
            col.insert_one({**item, "source": "sotong.go.kr",
                            "crawled_at": datetime.utcnow()})
            saved += 1

        time.sleep(0.5)

    client.close()
    print(f"\n완료! 스캔 {total}건 | 저장 {saved}건 | 스킵 {skipped}건")

if __name__ == "__main__":
    main()