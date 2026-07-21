"""
아이디어 발전 회의(ideation) "질문 주제 선정 및 전문가 의견 품질" 실제 모델 회귀 스크립트
================================================================================
실제 사용자 테스트에서 확인된 문제들이 재발하지 않는지 실제 OpenAI 모델로 확인한다.
  1) 문제·목표 사용자·핵심 가치·공모전 적합성이 정리되지 않았는데 로드맵/확장 기능을 질문.
  2) 한 질문에서 여러 쟁점을 동시에 물음.
  3) 기획/개발 전문가가 비슷한 결론과 제안을 반복함.
  4) 전문가들이 아이디어를 비판적으로 검토하지 않고 대부분 긍정함.
  5) 전문가 의견이 너무 길어서 읽기 어려움.
pytest 대상이 아니다 — ai/meeting/tests/test_ideation_question_topics.py는 topic 우선순위·
roadmap 선행 조건·분량 제한의 "배선"만 stub으로 결정적으로 검증하고, 실제 모델이 그 규칙을
따라 자연스러운 질문/의견을 만드는지는 검증하지 않는다. 이 스크립트가 그 부분을 담당한다.
판정 상당수는 실제 LLM 출력에 대한 휴리스틱(키워드/길이/유사도) 검사이므로 "참고용 신호"에
가깝다 — 미묘하게 어긋나는 경우 사람이 출력을 직접 읽고 판단해야 한다.

운영 코드/테스트 코드는 이 스크립트에 의존하지 않는다 (일회성 수동 검증 전용).

실행 (repo 루트에서, review-board conda env):
    OPENAI_API_KEY=sk-...  python scripts/run_ideation_question_quality_scenarios.py
    (PowerShell) $env:OPENAI_API_KEY="sk-..."; python scripts/run_ideation_question_quality_scenarios.py

    선택 환경변수:
      IDEATION_TEST_MODEL   기본값 gpt-4o-mini

API 키는 코드에 직접 넣지 않는다 — 반드시 OPENAI_API_KEY 환경변수로만 읽는다.

시나리오(요청 사항 그대로):
  1. 문제와 사용자 가치가 미확정인 상태에서 roadmap 질문이 생성되지 않는지.
  2. 한 질문에서 두 쟁점을 동시에 묻지 않는지(질문 문장 내 물음표 개수로 휴리스틱 판정).
  3. 공모전 주제와 아이디어가 약하게 연결될 때 위험을 지적하는지.
  4. 기획과 개발 전문가의 의견이 실질적으로 다른지(텍스트 유사도).
  5. 전문가 의견이 지정한 분량(judgment 200자/reason 400자/suggestion 300자/confirmed·
     unconfirmed 각 3개)을 지키는지.
  6. MVP 이후 질문이 바로 로드맵으로 넘어가지 않고 AI의 핵심 역할이나 차별성을 먼저
     확인하는지.

종료 코드:
    0 = 모든 시나리오 통과
    1 = OPENAI_API_KEY 미설정
    2 = 하나 이상의 시나리오에서 위반 발견
"""

from __future__ import annotations

import os
import sys
from difflib import SequenceMatcher
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MEETING_DIR = _REPO_ROOT / "ai" / "meeting"
if str(_MEETING_DIR) not in sys.path:
    sys.path.insert(0, str(_MEETING_DIR))

MODEL = os.environ.get("IDEATION_TEST_MODEL", "gpt-4o-mini")
MAX_JUDGMENT_CHARS = 200
MAX_REASON_CHARS = 400
MAX_SUGGESTION_CHARS = 300
MAX_LIST_ITEMS = 3
OPINION_SIMILARITY_THRESHOLD = 0.6

# 질문 주제별로 그럴듯한 답변을 미리 준비해 둔다 — 실제 모델이 어떤 topic을 고를지 미리
# 알 수 없으므로, 관찰된 pending_question_topic에 맞춰 대응한다.
CANNED_ANSWERS = {
    "problem": "동네 가게 사장님들이 반복되는 손님 문의에 일일이 답하느라 시간을 많이 뺏깁니다.",
    "target_user": "목표 사용자는 동네 카페나 미용실을 운영하는 소상공인입니다.",
    "core_value": "문의 응대 시간을 줄여주는 것이 핵심 가치입니다.",
    "contest_fit": "공모전이 요구하는 디지털 전환 취지에 맞게 자동 응대 도구를 제공합니다.",
    "differentiation": "기존 챗봇과 달리 소상공인 전용 FAQ에 특화되어 있습니다.",
    "mvp": "MVP는 자주 묻는 질문에 자동으로 답하는 기능입니다.",
    "data": "자주 묻는 질문과 답변 목록 데이터를 사장님이 직접 입력합니다.",
    "ai_role": "생성형 AI는 애매한 질문도 자연스럽게 이해해서 답하는 역할을 맡습니다.",
    "roadmap": "다음 단계로는 예약 관리 기능을 추가할 계획입니다.",
}

NOTICE_AND_CRITERIA = {
    "competition_name": "지역 소상공인 디지털전환 공모전",
    "notice_document": "실현가능성, 차별성, 사업성을 평가한다.",
}
USER_IDEA = {"description": "소상공인이 손님 문의에 자동으로 답하는 챗봇"}

# 시나리오 3(공모전 적합성) 전용 — 공모전 주제와 약하게 연결된 아이디어.
WEAK_FIT_NOTICE = {
    "competition_name": "일상생활의 긴급 문제 해결 공모전",
    "notice_document": "위급 상황을 조기에 감지하고 대응하는 긴급 문제 해결형 서비스를 우대한다.",
}
WEAK_FIT_USER_IDEA = {"description": "매일 물 마시기, 스트레칭 등 건강 습관을 기록하고 알려주는 앱"}


def make_llm_call():
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    def llm_call(prompt: str) -> str:
        resp = client.chat.completions.create(
            model=MODEL, messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"}
        )
        return resp.choices[0].message.content

    return llm_call


def _question_text(content: str) -> str:
    """_compose_question_content()가 만든 "[현재 판단]\\n...\\n\\n[핵심 질문]\\n..." 형식에서
    질문 부분만 뽑아낸다."""
    marker = "[핵심 질문]"
    idx = content.find(marker)
    return content[idx + len(marker):].strip() if idx >= 0 else content


def drive_conversation(llm_call, notice_and_criteria, user_idea, max_rounds=3, max_turns=16):
    """topic 우선순위/roadmap 선행 조건을 실제 모델로 끝까지 확인하기 위해, 관찰된
    pending_question_topic에 맞는 미리 준비된 답을 보내며 대화를 이어간다. 각 턴의
    (topic, resolved_topics_before, question_text)를 기록해 반환한다."""
    from graph import ROADMAP_PREREQUISITE_TOPICS, reply_ideation_conversation, start_ideation_conversation

    state = start_ideation_conversation(
        session_id="QQ-TOPIC",
        notice_and_criteria=notice_and_criteria,
        user_idea=user_idea,
        llm_call=llm_call,
        max_rounds=max_rounds,
    )
    turns = []
    violations = []

    for _ in range(max_turns):
        phase = state["phase"]
        if phase in ("finalized", "failed", "awaiting_user_decision"):
            break
        topic = state.get("pending_question_topic")
        resolved_before = list(state.get("resolved_topics") or [])
        question_message = state["messages"][-1] if state["messages"] else None
        question_text = _question_text(question_message["content"]) if question_message else ""
        turns.append({"topic": topic, "resolved_before": resolved_before, "question_text": question_text})

        if topic == "roadmap" and not ROADMAP_PREREQUISITE_TOPICS.issubset(set(resolved_before)):
            violations.append(
                f"선행 주제가 다 확인되지 않았는데 roadmap을 질문했습니다 — resolved={resolved_before}"
            )

        answer = CANNED_ANSWERS.get(topic, "네, 알겠습니다.")
        state = reply_ideation_conversation(previous_state=state, user_message=answer, llm_call=llm_call)

    return turns, violations, state


def check_roadmap_gating(llm_call) -> list[str]:
    print("\n=== 시나리오 1+6: roadmap 선행 조건, mvp 직후 roadmap으로 바로 넘어가지 않는지 ===")
    turns, violations, _ = drive_conversation(llm_call, NOTICE_AND_CRITERIA, USER_IDEA)
    for t in turns:
        print(f"  topic={t['topic']} resolved_before={t['resolved_before']}")
        print(f"    질문: {t['question_text'][:150]}")

    mvp_index = next((i for i, t in enumerate(turns) if t["topic"] == "mvp"), None)
    if mvp_index is not None and mvp_index + 1 < len(turns):
        next_topic = turns[mvp_index + 1]["topic"]
        if next_topic == "roadmap":
            violations.append(f"mvp 확인 직후 바로 roadmap을 질문했습니다(다음 topic={next_topic}).")
        else:
            print(f"  [OK] mvp 확인 직후 다음 topic={next_topic} (roadmap 아님)")
    return violations


def check_single_issue_per_question(llm_call) -> list[str]:
    print("\n=== 시나리오 2: 한 질문에서 두 쟁점을 동시에 묻지 않는지(물음표 개수 휴리스틱) ===")
    turns, _, _ = drive_conversation(llm_call, NOTICE_AND_CRITERIA, USER_IDEA)
    violations = []
    for t in turns:
        question_marks = t["question_text"].count("?") + t["question_text"].count("？")
        print(f"  topic={t['topic']} 물음표 개수={question_marks} 질문={t['question_text'][:150]}")
        if question_marks > 1:
            violations.append(f"topic={t['topic']} 질문에 물음표가 {question_marks}개 있습니다(여러 쟁점 의심): {t['question_text']}")
    return violations


def check_contest_fit_criticism(llm_call) -> list[str]:
    print("\n=== 시나리오 3: 공모전 주제와 약하게 연결될 때 위험을 지적하는지 ===")
    from graph import reply_ideation_conversation, start_ideation_conversation

    state = start_ideation_conversation(
        session_id="QQ-FIT",
        notice_and_criteria=WEAK_FIT_NOTICE,
        user_idea=WEAK_FIT_USER_IDEA,
        llm_call=llm_call,
        max_rounds=2,
    )
    # 두 질문에 모두 답해 기획/개발 의견까지 만든다.
    for _ in range(2):
        if state["phase"] not in ("awaiting_planning_answer", "awaiting_developer_answer"):
            break
        topic = state.get("pending_question_topic")
        answer = CANNED_ANSWERS.get(topic, "네, 알겠습니다.")
        state = reply_ideation_conversation(previous_state=state, user_message=answer, llm_call=llm_call)

    planning_opinions = [
        m for m in state["messages"] if m["speaker_id"] == "planning_expert" and m["message_type"] in ("opinion", "disagreement", "agreement")
    ]
    if not planning_opinions:
        return ["기획 전문가 의견이 생성되지 않아 공모전 적합성 검토를 확인할 수 없습니다."]

    risk_keywords = ["약합니다", "약하", "부족", "위험", "우려", "연결이 낮", "미흡"]
    opinion = planning_opinions[-1]
    text = opinion["content"]
    print(f"  기획 전문가 의견: {text}")
    if any(kw in text for kw in risk_keywords):
        print("  [OK] 공모전 적합성 위험을 지적하는 표현을 찾았습니다.")
        return []
    return ["공모전 주제와 약하게 연결된 아이디어인데도 기획 전문가 의견에서 위험을 지적하는 표현을 찾지 못했습니다."]


def check_experts_differ_and_length(llm_call) -> list[str]:
    print("\n=== 시나리오 4+5: 기획/개발 의견이 실질적으로 다른지 + 분량 제한 준수 ===")
    from graph import reply_ideation_conversation, start_ideation_conversation

    state = start_ideation_conversation(
        session_id="QQ-DIFF", notice_and_criteria=NOTICE_AND_CRITERIA, user_idea=USER_IDEA, llm_call=llm_call, max_rounds=2
    )
    for _ in range(2):
        if state["phase"] not in ("awaiting_planning_answer", "awaiting_developer_answer"):
            break
        topic = state.get("pending_question_topic")
        answer = CANNED_ANSWERS.get(topic, "네, 알겠습니다.")
        state = reply_ideation_conversation(previous_state=state, user_message=answer, llm_call=llm_call)

    violations = []
    opinions = [m for m in state["messages"] if m["message_type"] in ("opinion", "agreement", "disagreement")]
    for m in opinions:
        structured = m.get("structured") or {}
        judgment, reason, suggestion = structured.get("judgment", ""), structured.get("reason", ""), structured.get("suggestion", "")
        confirmed, unconfirmed = structured.get("confirmed", []), structured.get("unconfirmed", [])
        print(f"  [{m['speaker_id']}] judgment({len(judgment)}자)/reason({len(reason)}자)/suggestion({len(suggestion)}자)")
        print(f"    confirmed={len(confirmed)}개 unconfirmed={len(unconfirmed)}개")
        if len(judgment) > MAX_JUDGMENT_CHARS:
            violations.append(f"{m['speaker_id']} judgment가 {len(judgment)}자로 상한({MAX_JUDGMENT_CHARS}) 초과")
        if len(reason) > MAX_REASON_CHARS:
            violations.append(f"{m['speaker_id']} reason이 {len(reason)}자로 상한({MAX_REASON_CHARS}) 초과")
        if len(suggestion) > MAX_SUGGESTION_CHARS:
            violations.append(f"{m['speaker_id']} suggestion이 {len(suggestion)}자로 상한({MAX_SUGGESTION_CHARS}) 초과")
        if len(confirmed) > MAX_LIST_ITEMS:
            violations.append(f"{m['speaker_id']} confirmed가 {len(confirmed)}개로 상한({MAX_LIST_ITEMS}) 초과")
        if len(unconfirmed) > MAX_LIST_ITEMS:
            violations.append(f"{m['speaker_id']} unconfirmed가 {len(unconfirmed)}개로 상한({MAX_LIST_ITEMS}) 초과")

    planning = next((m for m in opinions if m["speaker_id"] == "planning_expert"), None)
    dev = next((m for m in opinions if m["speaker_id"] == "dev_expert"), None)
    if planning and dev:
        ratio = SequenceMatcher(None, planning["content"], dev["content"]).ratio()
        print(f"  기획/개발 의견 텍스트 유사도={ratio:.2f}")
        if ratio >= OPINION_SIMILARITY_THRESHOLD:
            violations.append(f"기획/개발 의견의 유사도가 {ratio:.2f}로 임계값({OPINION_SIMILARITY_THRESHOLD}) 이상입니다 — 결론이 반복될 수 있습니다.")
    else:
        violations.append("기획 또는 개발 전문가 의견이 생성되지 않았습니다.")

    return violations


def main() -> int:
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY 환경변수가 설정되어 있지 않습니다.", file=sys.stderr)
        return 1

    llm_call = make_llm_call()
    all_violations: list[str] = []
    all_violations += check_roadmap_gating(llm_call)
    all_violations += check_single_issue_per_question(llm_call)
    all_violations += check_contest_fit_criticism(llm_call)
    all_violations += check_experts_differ_and_length(llm_call)

    print("\n=== 결과 ===")
    if all_violations:
        for v in all_violations:
            print(f"  [FAIL] {v}", file=sys.stderr)
        return 2

    print("모든 시나리오 통과 — 질문 주제 선정과 전문가 의견 품질이 요청 기준을 만족합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
