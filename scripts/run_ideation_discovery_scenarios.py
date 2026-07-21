"""
아이디어 발전 회의(ideation) discovery(아이디어 발굴) 모드 수동 검증 스크립트
================================================================================
실제 OpenAI 모델로 "초기 아이디어 없이 시작 -> 후보 2~3개 생성 -> 후보 선택 -> refinement
전환"까지 discovery 모드 흐름이 실제로 동작하는지 눈으로 확인한다. pytest 대상이 아니다
(ai/meeting/tests/test_ideation_discovery_graph.py가 stub LLM으로 하는 구조 검증과는
목적이 다르다 — 이 스크립트는 "실제 모델이 후보를 서로 다르게 만드는지"를 확인한다).

운영 코드/테스트 코드는 이 스크립트에 의존하지 않는다 (일회성 수동 검증 전용).

실행 (repo 루트에서, review-board conda env):
    OPENAI_API_KEY=sk-...  python scripts/run_ideation_discovery_scenarios.py
    (PowerShell) $env:OPENAI_API_KEY="sk-..."; python scripts/run_ideation_discovery_scenarios.py

    선택 환경변수:
      IDEATION_TEST_MODEL   기본값 gpt-4o-mini
      IDEATION_SIMILARITY_THRESHOLD   기본값 0.55 (0~1, 낮을수록 엄격)

API 키는 코드에 직접 넣지 않는다 — 반드시 OPENAI_API_KEY 환경변수로만 읽는다.

성공 판정 기준(요청 사항):
  1) 후보가 2~3개 생성된다.
  2) 후보끼리 problem/target_user가 문자열 그대로 겹치지 않는다(완전 동일 금지).
  3) 후보끼리 핵심 내용(problem+target_user+core_value+solution+differentiation)의
     유사도가 IDEATION_SIMILARITY_THRESHOLD 미만이어야 한다 — "제목만 다르고 내용은
     사실상 같은" 후보를 잡아내기 위한 기준이다(difflib.SequenceMatcher 기반, 외부
     의존성 없이 대략적인 텍스트 유사도만 본다 — 정밀한 의미 유사도 판정이 아니다).
  4) 후보 선택("1번") 후 같은 요청 안에서 refinement 첫 질문까지 생성되고, phase가
     awaiting_planning_answer로 바뀐다.

종료 코드:
    0 = 모든 시나리오 + 성공 판정 기준 통과
    1 = OPENAI_API_KEY 미설정
    2 = discovery 후보 생성 자체가 실패(개수/스키마)
    3 = 후보 실질적 동일성 검사 실패("제목만 다른" 후보 발견)
    4 = 후보 선택 -> refinement 전환 검증 실패
"""

from __future__ import annotations

import os
import sys
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MEETING_DIR = _REPO_ROOT / "ai" / "meeting"
if str(_MEETING_DIR) not in sys.path:
    sys.path.insert(0, str(_MEETING_DIR))

MODEL = os.environ.get("IDEATION_TEST_MODEL", "gpt-4o-mini")
SIMILARITY_THRESHOLD = float(os.environ.get("IDEATION_SIMILARITY_THRESHOLD", "0.55"))

NOTICE_AND_CRITERIA = {
    "competition_name": "지역 소상공인 디지털전환 공모전",
    "notice_document": "실현가능성, 차별성, 사업성을 평가한다. 소상공인을 위한 실질적인 디지털 도구를 우대한다.",
}

_SIMILARITY_FIELDS = ("problem", "target_user", "core_value", "solution", "differentiation")


def _candidate_text(candidate: dict) -> str:
    return " ".join(str(candidate.get(field, "")) for field in _SIMILARITY_FIELDS)


def _similarity(a: dict, b: dict) -> float:
    return SequenceMatcher(None, _candidate_text(a), _candidate_text(b)).ratio()


def _check_candidates_are_substantively_distinct(candidates: list[dict]) -> list[str]:
    """제목만 다르고 실질적으로 같은 후보가 있는지 확인한다. 문제가 있으면 사람이 읽을 수
    있는 이유 문자열 목록을, 없으면 빈 리스트를 반환한다."""
    problems: list[str] = []

    problem_texts = [str(c.get("problem", "")).strip() for c in candidates]
    if len(set(problem_texts)) != len(problem_texts):
        problems.append("서로 다른 후보의 'problem' 필드가 문자열 그대로 완전히 동일합니다.")

    target_user_texts = [str(c.get("target_user", "")).strip() for c in candidates]
    if len(set(target_user_texts)) != len(target_user_texts):
        problems.append("서로 다른 후보의 'target_user' 필드가 문자열 그대로 완전히 동일합니다.")

    for a, b in combinations(candidates, 2):
        ratio = _similarity(a, b)
        if ratio >= SIMILARITY_THRESHOLD:
            problems.append(
                f"'{a.get('title')}'와(과) '{b.get('title')}'의 핵심 내용 유사도가 {ratio:.2f}로 "
                f"임계값({SIMILARITY_THRESHOLD}) 이상입니다 — 제목만 다르고 실질적으로 같은 후보일 수 있습니다."
            )

    return problems


def make_llm_call(label: str):
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    call_count = {"n": 0}

    def llm_call(prompt: str) -> str:
        call_count["n"] += 1
        resp = client.chat.completions.create(
            model=MODEL, messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"}
        )
        text = resp.choices[0].message.content
        print(f"  [{label} 호출#{call_count['n']}] {len(text)}자 응답")
        return text

    return llm_call


def dump_candidates(candidates: list[dict]) -> None:
    for c in candidates:
        print(f"    - [{c['candidate_id']}] {c['title']} (실현가능성={c.get('feasibility')})")
        print(f"      문제: {c['problem']}")
        print(f"      목표 사용자: {c['target_user']}")


def main() -> int:
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY 환경변수가 설정되어 있지 않습니다.", file=sys.stderr)
        return 1

    from graph import reply_ideation_conversation, start_ideation_conversation

    print("\n=== 초기 아이디어 없이 시작 -> discovery 모드로 후보 생성 ===")
    llm = make_llm_call("DISC")
    state = start_ideation_conversation(
        session_id="DISC-MANUAL", notice_and_criteria=NOTICE_AND_CRITERIA, user_idea={"description": ""}, llm_call=llm
    )
    print("  ideation_mode=", state["ideation_mode"], " phase=", state["phase"])
    candidates = state["idea_candidates"]
    if state["ideation_mode"] != "discovery" or state["phase"] != "awaiting_candidate_selection" or not (2 <= len(candidates) <= 3):
        print("후보 생성 자체가 실패했습니다(모드/phase/개수 확인).", file=sys.stderr)
        return 2
    dump_candidates(candidates)

    print("\n=== 후보 실질적 동일성 검사(성공 판정 기준) ===")
    distinctness_problems = _check_candidates_are_substantively_distinct(candidates)
    if distinctness_problems:
        for problem in distinctness_problems:
            print(f"  [FAIL] {problem}", file=sys.stderr)
        return 3
    print(f"  통과 — 모든 후보 쌍의 유사도가 {SIMILARITY_THRESHOLD} 미만입니다.")

    print("\n=== 후보 1번 선택 -> 같은 요청 안에서 refinement 첫 질문까지 생성 ===")
    state = reply_ideation_conversation(previous_state=state, user_message="1번", llm_call=llm)
    print("  phase=", state["phase"], " selected=", state["selected_idea"]["title"])
    print("  첫 refinement 질문:", state["messages"][-1]["content"][:200])
    if state["phase"] != "awaiting_planning_answer":
        print("후보 선택 후 refinement 전환에 실패했습니다.", file=sys.stderr)
        return 4

    print("\n모든 discovery 시나리오 + 성공 판정 기준 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
