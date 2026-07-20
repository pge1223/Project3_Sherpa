# 작성자: 경이
# 목적: LangGraph 위원/위원장 노드에서 쓸 실행 프롬프트를 조립한다.
#       공통 프롬프트(reviewer_prompt.txt / chair_prompt.txt)에 persona_cards.json 기반
#       페르소나 블록과 실행 컨텍스트(rubric/submission/evidence 등)를 <<...>> 토큰 치환으로 주입한다.
# import: 표준 라이브러리 json, pathlib. (외부 의존성 없음)
# 참고: 페르소나 프롬프트 prose(docs/prompts/persona_prompts.md)는 중복 저장하지 않고
#       구조화 카드(ai/meeting/personas/persona_cards.json)에서 render_persona_block()으로 생성한다.

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

PROMPTS_DIR = Path(__file__).resolve().parent
PERSONAS_DIR = PROMPTS_DIR.parent / "personas"
PERSONA_CARDS_PATH = PERSONAS_DIR / "persona_cards.json"

REVIEWER_TEMPLATE = "reviewer_prompt.txt"
CHAIR_TEMPLATE = "chair_prompt.txt"


def _read_text(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _as_text(obj: Any) -> str:
    """dict/list 는 JSON 문자열로, 이미 str 이면 그대로 사용."""
    return obj if isinstance(obj, str) else _json(obj)


@lru_cache(maxsize=1)
def load_persona_cards() -> dict[str, dict]:
    """persona_id -> persona card 매핑."""
    data = json.loads(PERSONA_CARDS_PATH.read_text(encoding="utf-8"))
    return {card["persona_id"]: card for card in data.get("personas", [])}


def get_persona_card(persona_id: str) -> dict:
    cards = load_persona_cards()
    if persona_id not in cards:
        raise KeyError(f"알 수 없는 persona_id: {persona_id!r}. 가능한 값: {sorted(cards)}")
    return cards[persona_id]


def reviewer_personas_for_domain(domain: str | None = None) -> list[str]:
    """도메인 태그로 위원(위원장 제외) persona_id 목록을 반환한다.
    실제 회의 참석자 선발·발언 순서는 LangGraph 빌더가 도메인 구성 파일에서 확정한다."""
    cards = load_persona_cards()
    result = []
    for pid, card in cards.items():
        if card.get("is_chair"):
            continue
        if domain is None or domain in card.get("domain_tags", []):
            result.append(pid)
    return result


def render_persona_block(card: dict) -> str:
    """persona card(구조화)를 프롬프트용 텍스트 블록으로 렌더링한다."""
    lines: list[str] = []
    lines.append(f"당신은 AI Review Board의 {card['display_name']}입니다. ({card.get('role', '')})")
    if card.get("mission"):
        lines.append(f"[미션] {card['mission']}")

    perspectives = card.get("evaluation_perspectives", [])
    if perspectives:
        lines.append("")
        lines.append("[평가 관점]")
        for p in perspectives:
            lines.append(f"- {p['name']}: {p['description']}")

    tone = card.get("tone", {})
    if tone:
        lines.append("")
        lines.append("[말투]")
        if tone.get("keywords"):
            lines.append(f"- 키워드: {', '.join(tone['keywords'])}")
        if tone.get("speaking_style"):
            lines.append(f"- {tone['speaking_style']}")
        if tone.get("preferred_structure"):
            lines.append(f"- 작성 순서: {' → '.join(tone['preferred_structure'])}")
        if tone.get("avoid_expressions"):
            avoid = ", ".join(f'"{e}"' for e in tone["avoid_expressions"])
            lines.append(f"- 피해야 할 표현: {avoid}")

    scope = card.get("scope", {})
    if scope.get("include"):
        lines.append("")
        lines.append("[포함 범위]")
        lines.extend(f"- {item}" for item in scope["include"])
    if scope.get("exclude"):
        lines.append("")
        lines.append("[제외 범위]")
        lines.extend(f"- {item}" for item in scope["exclude"])
    if scope.get("handoff_to"):
        lines.append("")
        lines.append("[전문 범위를 벗어난 판단 핸드오프]")
        for h in scope["handoff_to"]:
            lines.append(f"- {h['persona_id']}: {h['when']}")

    # 용준/Claude(2026-07-20): 아이디어 발전 회의(ideation) 전문가 카드에만 있는 선택 필드.
    # 기존 심사형 카드엔 이 키가 없으므로 없으면 그냥 건너뛴다(하위호환).
    if card.get("collaboration_stances"):
        lines.append("")
        lines.append("[발언 시 명시해야 하는 태도(stance) — 다음 중 하나를 선택]")
        lines.extend(f"- {s}" for s in card["collaboration_stances"])

    return "\n".join(lines)


def _render_evidence_guards(evidence_guards: Any | None) -> str:
    """(criterion_id, prompt_guard) 목록을 프롬프트용 텍스트로 렌더링한다(RAG-005 사전 판정).
    판정이 없으면(레거시 경로) 통상 평가 안내만 반환한다."""
    _default = "항목별 근거 충족도 판정이 제공되지 않았습니다. rubric에 따라 통상적으로 평가하세요."
    if not evidence_guards:
        return _default
    lines: list[str] = []
    for criterion_id, guard_text in evidence_guards:
        guard_text = (guard_text or "").strip()
        if guard_text:
            lines.append(f"- [{criterion_id}] {guard_text}")
    return "\n".join(lines) if lines else _default


def build_reviewer_prompt(
    persona_id: str,
    rubric: Any,
    submission: Any,
    retrieved_evidence: Any,
    previous_reviews: Any | None = None,
    evidence_guards: Any | None = None,
) -> str:
    """1~8번 위원용 실행 프롬프트를 조립한다. previous_reviews 기본값은 빈 배열(1회차).
    evidence_guards는 (criterion_id, prompt_guard) 목록(RAG-005 사전 판정)으로, 없으면
    통상 평가 안내가 들어간다."""
    card = get_persona_card(persona_id)
    if card.get("is_chair"):
        raise ValueError(f"{persona_id!r} 는 위원장입니다. build_chair_prompt()를 사용하세요.")
    template = _read_text(REVIEWER_TEMPLATE)
    replacements = {
        "<<PERSONA_BLOCK>>": render_persona_block(card),
        "<<RUBRIC_JSON>>": _as_text(rubric),
        "<<SUBMISSION_JSON>>": _as_text(submission),
        "<<RETRIEVED_EVIDENCE_JSON>>": _as_text(retrieved_evidence),
        "<<EVIDENCE_GUARD>>": _render_evidence_guards(evidence_guards),
        "<<PREVIOUS_REVIEWS_JSON>>": _as_text(previous_reviews if previous_reviews is not None else []),
    }
    for token, value in replacements.items():
        template = template.replace(token, value)
    return template


def build_chair_prompt(
    reviewer_results: Any,
    rubric: Any,
    evidence: Any | None = None,
    chair_persona_id: str = "review_chair",
) -> str:
    """위원장용 실행 프롬프트를 조립한다."""
    card = get_persona_card(chair_persona_id)
    template = _read_text(CHAIR_TEMPLATE)
    replacements = {
        "<<CHAIR_BLOCK>>": render_persona_block(card),
        "<<RUBRIC_JSON>>": _as_text(rubric),
        "<<REVIEWER_RESULTS_JSON>>": _as_text(reviewer_results),
        "<<EVIDENCE_JSON>>": _as_text(evidence if evidence is not None else []),
    }
    for token, value in replacements.items():
        template = template.replace(token, value)
    return template


# ============================================================================
# 용준/Claude(2026-07-20): 아이디어 발전 회의(ideation) 모드 프롬프트 빌더.
# 기존 build_reviewer_prompt/build_chair_prompt는 건드리지 않고 새 함수만 추가한다.
# 템플릿: ideation_common.txt(전문가 공통, reviewer_prompt.txt와 같은 패턴),
# ideation_facilitator_prompt.txt(라운드 열기/닫기), ideation_synthesis_prompt.txt(최종 종합).
# ============================================================================

IDEATION_TURN_TEMPLATE = "ideation_common.txt"
IDEATION_FACILITATOR_TEMPLATE = "ideation_facilitator_prompt.txt"
IDEATION_SYNTHESIS_TEMPLATE = "ideation_synthesis_prompt.txt"


def build_ideation_turn_prompt(
    persona_id: str,
    notice_and_criteria: Any,
    user_idea: Any,
    retrieved_evidence: Any,
    round_context: Any,
) -> str:
    """기획/개발 전문가 1턴 실행 프롬프트를 조립한다.

    round_context는 전체 회의록이 아니라 상태(ideation_state.py)가 미리 압축한
    {"round": int, "previous_turn": dict|None, "consensus_so_far": [str],
    "unresolved_issues": [str]} 형태다 — 토큰 사용량을 줄이기 위해 직전 발언 1개와
    누적 요약만 전달한다(요청 7번 "토큰 사용량 고려").
    """
    card = get_persona_card(persona_id)
    template = _read_text(IDEATION_TURN_TEMPLATE)
    replacements = {
        "<<PERSONA_BLOCK>>": render_persona_block(card),
        "<<NOTICE_AND_CRITERIA_JSON>>": _as_text(notice_and_criteria),
        "<<USER_IDEA_JSON>>": _as_text(user_idea),
        "<<RETRIEVED_EVIDENCE_JSON>>": _as_text(retrieved_evidence),
        "<<ROUND_CONTEXT_JSON>>": _as_text(round_context),
    }
    for token, value in replacements.items():
        template = template.replace(token, value)
    return template


def build_ideation_facilitator_prompt(
    notice_and_criteria: Any,
    user_idea: Any,
    round_number: int,
    max_rounds: int,
    turns_this_round: Any,
    consensus_so_far: Any,
    unresolved_issues: Any,
) -> str:
    """라운드 시작(쟁점 정리) + 라운드 종료(합의/이견/다음 행동 판단) 겸용 프롬프트."""
    card = get_persona_card("ideation_facilitator")
    template = _read_text(IDEATION_FACILITATOR_TEMPLATE)
    replacements = {
        "<<FACILITATOR_BLOCK>>": render_persona_block(card),
        "<<NOTICE_AND_CRITERIA_JSON>>": _as_text(notice_and_criteria),
        "<<USER_IDEA_JSON>>": _as_text(user_idea),
        "<<ROUND_NUMBER>>": str(round_number),
        "<<MAX_ROUNDS>>": str(max_rounds),
        "<<TURNS_THIS_ROUND_JSON>>": _as_text(turns_this_round),
        "<<CONSENSUS_SO_FAR_JSON>>": _as_text(consensus_so_far if consensus_so_far is not None else []),
        "<<UNRESOLVED_ISSUES_JSON>>": _as_text(unresolved_issues if unresolved_issues is not None else []),
    }
    for token, value in replacements.items():
        template = template.replace(token, value)
    return template


def build_ideation_synthesis_prompt(
    notice_and_criteria: Any,
    user_idea: Any,
    all_turns: Any,
    consensus_so_far: Any,
    unresolved_issues: Any,
) -> str:
    """회의 종료 시 최종 아이디어 제안서를 조립하는 프롬프트."""
    card = get_persona_card("ideation_facilitator")
    template = _read_text(IDEATION_SYNTHESIS_TEMPLATE)
    replacements = {
        "<<FACILITATOR_BLOCK>>": render_persona_block(card),
        "<<NOTICE_AND_CRITERIA_JSON>>": _as_text(notice_and_criteria),
        "<<USER_IDEA_JSON>>": _as_text(user_idea),
        "<<ALL_TURNS_JSON>>": _as_text(all_turns),
        "<<CONSENSUS_SO_FAR_JSON>>": _as_text(consensus_so_far if consensus_so_far is not None else []),
        "<<UNRESOLVED_ISSUES_JSON>>": _as_text(unresolved_issues if unresolved_issues is not None else []),
    }
    for token, value in replacements.items():
        template = template.replace(token, value)
    return template


if __name__ == "__main__":
    # 스모크 테스트: 실제 LLM 호출 없이 프롬프트 조립만 확인한다.
    demo_rubric = {
        "rubric_id": "RUBRIC-DEMO",
        "total_max_score": 30,
        "criteria": [
            {"criterion_id": "marketability", "criterion_name": "시장성", "max_score": 30, "required": True},
        ],
    }
    demo_submission = {"document_name": "데모.pdf", "text": "타깃 고객은 소규모 오프라인 매장이다."}
    demo_evidence = [{"source_id": "DOC-DEMO", "chunk_id": "CHUNK-1", "page": 1, "text": "..."}]

    reviewers = reviewer_personas_for_domain("startup")
    print("startup 위원 후보:", reviewers)

    rp = build_reviewer_prompt("business_strategy", demo_rubric, demo_submission, demo_evidence)
    cp = build_chair_prompt([], demo_rubric, demo_evidence)

    assert "<<" not in rp, "reviewer 프롬프트에 치환되지 않은 토큰이 있습니다"
    assert "<<" not in cp, "chair 프롬프트에 치환되지 않은 토큰이 있습니다"
    assert "사업전략 전문가" in rp
    assert "위원장" in cp
    print(f"reviewer_prompt 길이: {len(rp)}  / chair_prompt 길이: {len(cp)}")
    print("OK: 프롬프트 조립 및 토큰 치환 정상")

    # 용준/Claude(2026-07-20): ideation 프롬프트 빌더 스모크 테스트.
    demo_notice = {"notice_summary": "지역 소상공인 디지털전환 공모전", "criteria": ["실현가능성", "차별성"]}
    demo_idea = {"title": "동네 가게 챗봇", "description": "소상공인이 손님 문의에 자동으로 답하는 챗봇"}
    demo_round_context = {"round": 1, "previous_turn": None, "consensus_so_far": [], "unresolved_issues": []}

    tp_planning = build_ideation_turn_prompt("planning_expert", demo_notice, demo_idea, demo_evidence, demo_round_context)
    tp_dev = build_ideation_turn_prompt("dev_expert", demo_notice, demo_idea, demo_evidence, demo_round_context)
    fp = build_ideation_facilitator_prompt(demo_notice, demo_idea, 1, 3, [], [], [])
    sp = build_ideation_synthesis_prompt(demo_notice, demo_idea, [], [], [])

    assert "<<" not in tp_planning, "ideation 기획 전문가 프롬프트에 치환되지 않은 토큰이 있습니다"
    assert "<<" not in tp_dev, "ideation 개발 전문가 프롬프트에 치환되지 않은 토큰이 있습니다"
    assert "<<" not in fp, "ideation 진행자 프롬프트에 치환되지 않은 토큰이 있습니다"
    assert "<<" not in sp, "ideation 종합 프롬프트에 치환되지 않은 토큰이 있습니다"
    assert "당신은 AI Review Board의 기획 전문가입니다" in tp_planning
    assert "당신은 AI Review Board의 개발 전문가입니다" in tp_dev
    assert "당신은 AI Review Board의 개발 전문가입니다" not in tp_planning
    assert "당신은 AI Review Board의 기획 전문가입니다" not in tp_dev
    assert "회의 진행자" in fp
    print(f"ideation_turn(planning) 길이: {len(tp_planning)} / ideation_turn(dev) 길이: {len(tp_dev)}")
    print(f"ideation_facilitator 길이: {len(fp)} / ideation_synthesis 길이: {len(sp)}")
    print("OK: ideation 프롬프트 조립 및 토큰 치환 정상")
