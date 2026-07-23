# 작성자: 용준/Claude(2026-07-20)
# 목적: "아이디어 발전 회의(ideation)"의 대화형(턴마다 사용자 응답을 기다리는) 버전 State.
#       기존 IdeationState(ideation_state.py)는 한 번의 그래프 실행 안에서
#       planning_expert -> dev_expert -> planning_expert_revise -> facilitator가 전부
#       돌고 나서야 사용자 질문 여부를 판단하므로, "기획 질문 직후 정지 -> 사용자 답변 ->
#       개발 질문 직후 정지 -> 사용자 답변 -> 두 전문가 의견 보완"이라는 요구를 그대로
#       담을 수 없다(질문 하나당 정지 지점이 필요). 이 State는 그 정지 지점들을 phase로
#       명시적으로 표현한다. 기존 IdeationState/그래프는 전혀 수정하지 않는다.
# import: 표준 라이브러리 operator/typing만 사용(외부 의존성 없음).

from __future__ import annotations

import operator
import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal, TypedDict

# 대화 진행 단계. "실패"는 기존 IdeationStage와 통일해 한국어 대신 영문 slug를 쓴다 —
# 이 phase는 프론트가 직접 분기 렌더링에 쓰는 값이라(요구된 8개 상태 그대로) 계약을
# 영문으로 고정해 프론트/백엔드 문자열 매칭 실수를 줄인다.
#
# 용준/Claude(2026-07-21): discovery(아이디어 발굴) 모드용 phase 3개를 추가한다 —
# candidate_generation(기획 후보 생성 -> 개발 실현가능성 검토, 정지 없이 연속 실행),
# awaiting_candidate_selection(후보 제시 후 사용자 선택 대기, 정지 지점),
# candidate_selection(사용자의 선택/결합/재추천/전문가추천 요청 처리). refinement 전용
# phase(planning_question 등)는 값 하나도 바꾸지 않는다 — discovery는 이 phase들을 거쳐
# 최종적으로 정확히 refinement의 "planning_question" phase로 합류한다(요청 4번).
ConvPhase = Literal[
    "candidate_generation",
    "awaiting_candidate_selection",
    "candidate_selection",
    "planning_question",
    "awaiting_planning_answer",
    "developer_question",
    "awaiting_developer_answer",
    "expert_discussion",
    "awaiting_user_decision",
    "finalized",
    "failed",
    # 내부 전이용 값 — API/프론트에 노출되는 공개 상태에는 포함되지 않는다.
    # request_finalize()가 잠깐 이 값으로 바꿔 그래프 진입 라우팅(_route_entry)이
    # synthesis 노드로 가게 만들 뿐, synthesis 노드가 끝나면 항상 "finalized" 또는
    # "failed"로 바뀌므로 이 값이 API 응답에 그대로 나가는 일은 없다.
    "finalizing",
]

# 용준/Claude(2026-07-21, 요청: 전문가 라운드테이블 전환): "interjection"은 사용자가 진행자의
# 직접 질문(pending_question)에 답한 게 아니라, 라운드 사이에 자발적으로 끼어든 발언이다 —
# reply_ideation_conversation이 previous_state.get("pending_question") 존재 여부로 "answer"와
# "interjection"을 구분한다(요청 6번: "user_interjection으로 기록").
MessageType = Literal["question", "answer", "interjection", "opinion", "agreement", "disagreement", "summary"]

_TERMINAL_ENTRY_PHASES = {
    "candidate_generation",
    "candidate_selection",
    "planning_question",
    "developer_question",
    "expert_discussion",
}

IdeationMode = Literal["refinement", "discovery"]

# 용준/Claude(2026-07-21): 질문 생성 노드가 이번 질문에서 어떤 종류의 답을 기대하는지
# 표시하는 값. sufficiency 판정이 "답변 충분성"과 "아이디어 완성도"를 혼동하지 않도록
# 돕는다 — preference/selection(선호·선택·방향성)은 하나를 명확히 고르기만 해도
# 충분하고, definition/constraint/evidence/specification은 상대적으로 더 구체적인
# 내용을 요구한다(ideation_conv_sufficiency.txt 참고). 질문 노드가 이 값을 만들지
# 못하거나(구버전 응답 등) 유효하지 않은 값을 반환하면 None으로 저장하고, sufficiency
# 프롬프트는 그 경우 기존의 일반 기준으로 판정한다(하위 호환 — 이 값은 있으면 정확도를
# 높이는 보조 정보이지, 없다고 판정 자체가 막히지 않는다).
ExpectedAnswerType = Literal["preference", "selection", "definition", "constraint", "evidence", "specification"]

# 용준/Claude(2026-07-21, 질문 주제 구조화): 실제 사용자 테스트에서 "문제·목표 사용자·핵심
# 가치·공모전 적합성이 정리되지 않았는데 로드맵부터 질문"하거나 "한 질문에서 여러 쟁점을
# 동시에 묻는" 문제가 확인됐다. 이를 막기 위해 질문 하나가 다루는 주제를 명시적인 값
# (question_topic)으로 구조화하고, 그 우선순위를 코드가 강제한다 — 이 순서는 "문제 정의가
# 안 됐는데 확장 로드맵부터 묻는" 실패를 원천적으로 막기 위한 것이다(요청 목표 1~9번 순서
# 그대로). 모든 주제를 기계적으로 다 물어야 하는 것은 아니다 — 이미 resolved_topics에
# 있으면 건너뛴다(아래 remaining_topics_for 참고).
QuestionTopic = Literal[
    "problem", "target_user", "core_value", "contest_fit", "differentiation", "mvp", "data", "ai_role", "roadmap"
]

TOPIC_PRIORITY: tuple[str, ...] = (
    "problem",
    "target_user",
    "core_value",
    "contest_fit",
    "differentiation",
    "mvp",
    "data",
    "ai_role",
    "roadmap",
)

# roadmap(확장 기능/도입 순서)은 이 5개 주제가 모두 resolved_topics에 있어야만 질문할 수
# 있다(요청 2번 — "확장 기능과 로드맵을 너무 일찍 질문"하는 문제의 직접적인 원인 제거).
ROADMAP_PREREQUISITE_TOPICS: frozenset[str] = frozenset({"problem", "target_user", "core_value", "contest_fit", "mvp"})


def remaining_topics_for(resolved_topics: list[str] | None) -> list[str]:
    """아직 확인되지 않은 주제를 우선순위 순서로 반환한다. roadmap의 선행 주제
    (ROADMAP_PREREQUISITE_TOPICS)가 모두 resolved_topics에 없으면 roadmap 자체를 목록에서
    제외한다 — 질문 노드가 애초에 roadmap을 고를 수 없는 후보 목록만 보게 하는 것이,
    "질문 규칙으로만 금지"하는 것보다 더 확실한 강제 방법이다. resolved_topics가 None이면
    (구버전 state) 빈 리스트로 취급한다(하위 호환)."""
    resolved_set = set(resolved_topics or [])
    remaining = [topic for topic in TOPIC_PRIORITY if topic not in resolved_set]
    if "roadmap" in remaining and not ROADMAP_PREREQUISITE_TOPICS.issubset(resolved_set):
        remaining = [topic for topic in remaining if topic != "roadmap"]
    return remaining

# 용준/Claude(2026-07-21): ideation_mode는 세션이 "최초 진입할 때" discovery였는지
# refinement였는지만 기록한다(initial_conv_state가 딱 한 번 결정하고 이후 절대 바뀌지
# 않음) — 그런데 discovery 세션도 후보 선택 후에는 refinement와 동일한 질문/의견 흐름을
# 탄다. 프론트가 ideation_mode만 보고 배지를 표시하면 후보 선택 후에도 계속 "아이디어
# 발굴 모드"로 잘못 표시된다. active_stage는 그 문제를 풀기 위해 "현재 진행 단계"를
# 별도로 노출한다 — phase(그래프 내부 상태 기계 값, 세분화돼 있고 일부는 API에 절대
# 노출되지 않는 전이용 값)와 달리, active_stage는 프론트 배지 전용의 넓은 4단계
# 요약이다.
ActiveStage = Literal["candidate_discovery", "candidate_selection", "refinement", "finalized"]

# phase -> active_stage 매핑. candidate_generation/awaiting_candidate_selection은 아직
# 후보를 고르지 않은 단계라 "candidate_discovery"(아이디어 발굴 모드), candidate_selection은
# 사용자의 선택/결합/재추천 요청을 처리하는 중(그래프 내부 전이만으로 존재하고 API 응답에
# phase 자체로는 절대 노출되지 않지만, active_stage 매핑은 완전성을 위해 모든 phase를
# 다룬다), planning_question부터 awaiting_user_decision까지는 후보 선택이 끝나고 아이디어를
# 다듬는 "refinement"(아이디어 발전 모드), finalized/finalizing은 "finalized"다. failed는
# 별도로 처리한다(고정 4단계에 없음 — 아래 active_stage_for 참고).
_PHASE_TO_ACTIVE_STAGE: dict[str, ActiveStage] = {
    "candidate_generation": "candidate_discovery",
    "awaiting_candidate_selection": "candidate_discovery",
    "candidate_selection": "candidate_selection",
    "planning_question": "refinement",
    "awaiting_planning_answer": "refinement",
    "developer_question": "refinement",
    "awaiting_developer_answer": "refinement",
    "expert_discussion": "refinement",
    "awaiting_user_decision": "refinement",
    "finalized": "finalized",
    "finalizing": "finalized",
}


def active_stage_for(phase: str) -> ActiveStage | Literal["failed"]:
    """phase(세분화된 그래프 상태)를 프론트 배지용 넓은 진행 단계로 축약한다. refinement
    모드로 시작한 세션은 처음부터 "refinement"이고, discovery 모드로 시작한 세션은 후보
    선택 전까지 "candidate_discovery"였다가 선택 확정 순간부터 "refinement"로 바뀐다 —
    ideation_mode(최초 진입 모드, 절대 안 바뀜)와 달리 이 값은 세션 도중 바뀌는 것이
    핵심이다."""
    if phase == "failed":
        return "failed"
    return _PHASE_TO_ACTIVE_STAGE.get(phase, "refinement")


class DiscussionRoundRecord(TypedDict):
    """용준/Claude(2026-07-21, 요청: 위원 간 실제 회의로 개편): expert_discussion 라운드
    1회가 만든 발언들의 텍스트 스냅샷. messages(원본 발언 전체)와 별도로 이 요약을 두는
    이유는, 다음 단계(synthesis 등)가 "이번 라운드에 정확히 무슨 입장 변화가 있었는지"를
    messages 전체를 다시 훑지 않고 바로 참조할 수 있게 하기 위함이다 — content는 messages와
    중복 저장되지만(참조가 아니라 텍스트 스냅샷), 그래야 이후 다른 세션 필드처럼 dict로
    바로 직렬화해 API 응답/프롬프트에 넘기기 쉽다."""

    round: int
    planning_position: str
    development_review: str
    revised_proposal: str | None
    facilitator_summary: str
    needs_user_decision: bool


class ConvMessage(TypedDict):
    message_id: str
    speaker_id: str
    speaker_name: str
    role: str
    round: int
    message_type: MessageType
    content: str
    referenced_message_ids: list[str]
    evidence: list[dict]
    created_at: str
    # 용준/Claude(2026-07-21, 전문가 의견 UX 개선): opinion/agreement/disagreement 메시지의
    # judgment/reason/suggestion/confirmed/unconfirmed를 필드별로 담은 선택 정보 — content
    # 문자열(기존 그대로 유지)과 별개로, 프런트가 "판단/제안은 기본 노출, 근거·확정·미확정은
    # 상세 보기로 접기"를 구현할 수 있도록 순수 추가한 필드다. content가 없어지는 게 아니므로
    # structured를 모르는 기존 클라이언트는 영향받지 않는다. 질문/답변/설명/요약 메시지는
    # 항상 None이다.
    structured: dict | None


class IdeationConvState(TypedDict):
    """대화형 회의 세션 1개가 그래프 호출 사이(=HTTP 요청 사이)에 들고 다니는 상태.

    messages는 시간순으로 이어붙이는 리스트다(리듀서 operator.add) — 기존
    IdeationState.turns와 같은 이유(순서가 실제 대화 순서를 그대로 반영해야 함)다.
    phase가 이 State의 핵심이다: 그래프는 매 호출마다 phase를 보고 어느 노드부터
    시작할지 결정하고(ideation_conv_build.py::_route_entry), 실행한 노드는 다음에
    무엇을 해야 하는지를 나타내는 새 phase를 반환한다. "awaiting_*"과
    "awaiting_user_decision"은 그래프가 아니라 API 레이어가 사용자 입력을 받을 때까지
    멈춰 있는 지점이다(그래프 자신은 이 phase들로는 절대 진입하지 않고, 오직
    이 phase로 "끝난다").
    """

    session_id: str
    notice_and_criteria: dict
    user_idea: dict
    round: int
    max_rounds: int
    messages: Annotated[list[ConvMessage], operator.add]
    phase: ConvPhase
    pending_question: str | None
    # pending_question과 함께 세팅/리셋된다(질문 노드가 생성할 때 채우고,
    # apply_user_answer가 다음 단계로 넘어갈 때 None으로 되돌린다) — pending_question이
    # 가리키는 "지금 이 질문"이 어떤 종류의 답을 기대하는지에 대한 보조 정보다.
    pending_expected_answer_type: str | None
    # 용준/Claude(2026-07-21, 질문 주제 구조화): pending_question이 다루는 주제
    # (TOPIC_PRIORITY 중 하나). pending_question/pending_expected_answer_type과 함께
    # 세팅/리셋된다. 구버전 저장 state에는 이 키가 없을 수 있으므로 읽는 쪽은 항상
    # `.get("pending_question_topic")`로 접근한다(하위 호환).
    pending_question_topic: str | None
    # 사용자가 "answer"로 판정된 답을 해서 실제로 다음 단계로 진행한 주제만 담는다 —
    # clarification_request/insufficient_answer/재질문 진행 중/구조화 응답 실패는 이
    # 리스트에 추가되지 않는다(ideation_conv_run.py::_apply_answer_sufficiency_gate 참고).
    # 구버전 저장 state에는 이 키가 없을 수 있으므로 읽는 쪽은 항상
    # `.get("resolved_topics", [])`로 접근한다(하위 호환).
    resolved_topics: list[str]
    consensus: list[str]
    unresolved_issues: list[str]
    idea_proposal: dict | None
    failed_node: str | None
    llm_calls_used: int
    # 용준/Claude(2026-07-20): 같은 쟁점(pending_question)으로 재질문한 횟수. 사용자가
    # 질문에 답할 때마다 answer_sufficiency 판정을 거치는데, 무한 재질문을 막기 위해
    # 이 값이 retry_cap(ideation_conv_run.py::_MAX_ANSWER_RETRY)에 도달하면 판정 결과와
    # 무관하게 다음 단계로 강제 진행한다. 재질문이 아니라 다음 단계로 넘어갈 때마다 0으로
    # 리셋된다(쟁점이 바뀌었으므로).
    answer_retry_count: int

    # 용준/Claude(2026-07-21): discovery(아이디어 발굴) 모드 전용 필드. refinement 세션에서는
    # ideation_mode="refinement" 외에는 전부 초기값(빈 값)에서 바뀌지 않는다 — 요청 2번
    # "모드 판단을 여러 노드에서 반복하지 말고 시작 시 결정한 ideation_mode를 그래프 전체에서
    # 사용" — initial_conv_state()가 세션 시작 시 딱 한 번 결정해서 저장하고, 이후 모든 노드는
    # 이 필드를 읽기만 한다(다시 계산하지 않는다).
    ideation_mode: IdeationMode
    initial_idea: str | None
    contest_analysis: dict | None
    # 현재 유효한 후보 목록 — "다시 추천" 시 이 리스트가 교체된다.
    idea_candidates: list[dict]
    # 최초로 생성된 후보 목록 — 재추천으로 idea_candidates가 바뀌어도 이 값은 보존된다
    # (요청 8번 "discovery 모드의 최종 결과에는 최초 생성 후보... 이력을 포함").
    original_idea_candidates: list[dict]
    selected_idea: dict | None
    selection_reason: str | None
    # "다시 추천" 요청 횟수 — ideation_conv_discovery.py::MAX_CANDIDATE_REGENERATIONS에
    # 도달하면 더 이상 LLM을 호출해 후보를 재생성하지 않는다(요청: 무한 반복/LLM 호출 제한
    # 우회 방지).
    candidate_regeneration_count: int

    # 용준/Claude(2026-07-21, 후보 결합 컨텍스트 보존): 사용자가 "1번과 2번 결합"처럼
    # 후보를 선택/결합/추천한 직후, 그 요청이 refinement(질문/의견) 단계로 넘어가면서
    # 사라지지 않도록 별도로 보존하는 필드들 — conversation_context의 최근 메시지에 우연히
    # 남아있는 것에 기대지 않고, 질문 프롬프트가 구조화된 형태로 명시적으로 참조할 수 있게
    # 한다(ideation_conv_nodes.py::_selection_context_for 참고). selected_idea가 확정되지
    # 않는 경우(결합 적합도 low로 재질문하는 중)에도 이 필드들은 채워질 수 있다 —
    # selected_idea만 아직 None/이전 값일 뿐이다.
    selection_intent: str | None
    # 사용자가 후보 선택/결합을 요청한 원문 메시지 그대로.
    user_selection_message: str | None
    # 선택/결합 대상이 된 원본 후보(들)의 전체 필드(title/problem/target_user/core_value/
    # main_features 등) — 결합으로 새로 만들어진 selected_idea와 달리 이 값들은 병합 전
    # 원본 그대로다.
    source_candidates: list[dict]
    # candidate_selection 노드가 "combine" 해석 시 함께 만드는 결합 분석 결과(공통 문제/
    # 공통 가치/결합 적합도/주 기능/보조 기능/충돌 지점/미확정 사항). combine이 아니면 None.
    merge_analysis: dict | None

    # 용준/Claude(2026-07-21, 요청: 위원 간 실제 회의로 개편): expert_discussion phase가
    # 실행될 때마다(라운드마다) 1건씩 쌓인다(리듀서 operator.add — messages와 같은 원칙).
    # 구버전 저장 state에는 이 키가 없을 수 있으므로 읽는 쪽은 항상
    # `.get("discussion_rounds", [])`로 접근한다(하위 호환).
    discussion_rounds: Annotated[list[DiscussionRoundRecord], operator.add]

    # 용준/Claude(2026-07-21, 요청: 위원 간 실제 회의로 개편): 이번 라운드의 discussion 서브
    # 그래프(planning_expert_discussion -> dev_expert_discussion -> [선택적 revision] ->
    # discussion_facilitator)가 노드 사이에서 주고받는 임시 값들. Annotated(operator.add)가
    # 아니므로 매 라운드 노드가 반환하면 그대로 덮어써진다(messages처럼 누적하지 않는다) —
    # discussion_facilitator가 이번 라운드 값만 읽으면 되기 때문이다. 구버전 저장 state에는
    # 이 키들이 없을 수 있으므로 읽는 쪽은 항상 `.get(...)`로 접근한다(하위 호환).
    discussion_planning_position: dict | None
    discussion_development_review: dict | None
    discussion_revised_proposal: dict | None
    # dev_expert_discussion(review 단계)가 정한 다음 행동("continue_round"/
    # "await_user_decision") — 이 값 자체는 discussion_facilitator가 절대 바꾸지 않는다
    # (요청: 기존에 검증된 라운드 진행/max_rounds 강제 로직을 그대로 재사용).
    discussion_next_action: str | None
    # dev_expert_discussion(review 단계)가 고른 stance — planning_expert_revision을 실행할지
    # 결정하는 조건부 엣지(ideation_conv_build.py::_route_after_review)가 참조한다.
    discussion_review_stance: str | None

    # 가은/Claude(2026-07-22, 요청: 아이디어 기획 캔버스 자동 갱신 — 경이 협의 완료): 프론트
    # 오른쪽 패널 '아이디어 기획 캔버스'의 최신 값(problem/target_user/core_value/solution/
    # differentiation/feasibility/risks/contest_fit — selected_idea와 같은 키 이름을 써서
    # 프론트가 idea_canvas ?? selected_idea 폴백만으로 그릴 수 있게 한다). 매 라운드가 끝날
    # 때 canvas_update 노드(ideation_conv_nodes.py::make_canvas_update_node)가 덮어쓴다.
    # 갱신 실패 시에는 직전 값이 그대로 유지된다(비치명적). 구버전 저장 state에는 이 키가
    # 없을 수 있으므로 읽는 쪽은 항상 `.get("idea_canvas")`로 접근한다(하위 호환).
    idea_canvas: dict | None

    # 가은/Claude(2026-07-22, 요청: 신청양식 항목 약한 주입): 공모전 신청양식에서 추출한
    # 항목 목록([{field_name, description, char_limit}], 양식에 있는 만큼 전부 — 개수
    # 상한 없음). 세션 시작 시 한 번
    # 채워지고 이후 절대 바뀌지 않는다(discussion_rounds처럼 매 라운드 갱신되는 값이
    # 아니다). make_conv_discussion_node가 매 발언 프롬프트에 "참고 자료"로만 주입한다
    # (질문 주제·순서는 여전히 TOPIC_PRIORITY가 결정 — 이 값은 같은 주제를 물을 때 표현만
    # 다듬는 데 쓰인다, ideation_conv_discussion.txt의 [신청양식 참고 규칙] 참고). 없으면
    # 빈 리스트(양식 미등록) — 구버전 저장 state에는 이 키가 없을 수 있으므로 읽는 쪽은
    # 항상 `.get("application_form_items", [])`로 접근한다(하위 호환).
    application_form_items: list[dict]


def _extract_initial_idea_text(user_idea: dict | str | None) -> str:
    """user_idea에서 trim된 초기 아이디어 텍스트를 뽑아낸다. dict({"description": ...})와
    plain str을 모두 받아들인다 — 호출부(ideation_conv_run.py::start_ideation_conversation)의
    기존 시그니처(user_idea: dict)를 그대로 유지하면서, 이 함수 안에서만 "trim 결과가
    비어 있는지"로 모드를 결정하기 위함이다(요청 2번: 서버가 trim 결과 기준으로 자동 결정)."""
    if isinstance(user_idea, dict):
        return str(user_idea.get("description") or "").strip()
    if isinstance(user_idea, str):
        return user_idea.strip()
    return ""


def build_roundtable_opening_message(idea_text: str, round_number: int = 1) -> ConvMessage:
    """용준/Claude(2026-07-21, 요청: 전문가 라운드테이블 전환): 라운드테이블 진입 직전
    진행자의 안건 제시 메시지를 만든다. LLM을 부르지 않는다 — 사용자가 이미 입력한 텍스트를
    그대로 인용해 안건으로 재진술할 뿐이라 사실 왜곡 위험이 없고, LLM 호출 상한을 소비하지
    않는다. speaker_name/role은 페르소나 카드 조회 없이 고정값을 쓴다
    (ideation_conv_run.py::_new_facilitator_message와 동일한 기존 관례)."""
    idea = (idea_text or "").strip() or "제출하신 아이디어"
    content = f"오늘은 '{idea}'에 대한 문제와 구현 범위를 논의하겠습니다."
    return ConvMessage(
        message_id=f"MSG-{uuid.uuid4().hex[:10]}",
        speaker_id="ideation_facilitator",
        speaker_name="회의 진행자",
        role="진행자",
        round=round_number,
        message_type="summary",
        content=content,
        referenced_message_ids=[],
        evidence=[],
        created_at=datetime.now(timezone.utc).isoformat(),
        structured=None,
    )


def initial_conv_state(
    session_id: str,
    notice_and_criteria: dict,
    user_idea: dict,
    max_rounds: int = 3,
    application_form_items: list[dict] | None = None,
) -> IdeationConvState:
    """준비 상태. user_idea(trim 결과)가 있으면 refinement로 시작한다 — 용준/Claude(2026-07-21,
    요청: 전문가 라운드테이블 전환) 진행자의 안건 제시 메시지(LLM 호출 없음, 위
    build_roundtable_opening_message 참고)를 messages에 먼저 넣고, phase는 더 이상
    "planning_question"(1:1 인터뷰 진입점)이 아니라 "expert_discussion"(라운드테이블
    진입점)이다 — 기획/개발 위원이 서로를 상대로 먼저 토론하고, 사용자에게 직접 질문하는
    것은 진행자만 한다. 비어 있으면 discovery로 시작해 후보 생성 단계(candidate_generation)
    부터 진행한다(요청 1~2번, 변경 없음). ideation_mode는 여기서 딱 한 번 결정되어 이후
    그래프 전체가 이 값을 그대로 읽는다."""
    initial_idea = _extract_initial_idea_text(user_idea)
    mode: IdeationMode = "refinement" if initial_idea else "discovery"
    opening_messages = [build_roundtable_opening_message(initial_idea, round_number=1)] if mode == "refinement" else []
    return IdeationConvState(
        session_id=session_id,
        notice_and_criteria=notice_and_criteria,
        user_idea={"description": initial_idea} if initial_idea else {},
        round=1,
        max_rounds=max_rounds,
        messages=opening_messages,
        phase="expert_discussion" if mode == "refinement" else "candidate_generation",
        pending_question=None,
        pending_expected_answer_type=None,
        pending_question_topic=None,
        resolved_topics=[],
        consensus=[],
        unresolved_issues=[],
        idea_proposal=None,
        failed_node=None,
        llm_calls_used=0,
        answer_retry_count=0,
        ideation_mode=mode,
        initial_idea=initial_idea or None,
        contest_analysis=None,
        idea_candidates=[],
        original_idea_candidates=[],
        selected_idea=None,
        selection_reason=None,
        candidate_regeneration_count=0,
        selection_intent=None,
        user_selection_message=None,
        source_candidates=[],
        merge_analysis=None,
        discussion_rounds=[],
        discussion_planning_position=None,
        discussion_development_review=None,
        discussion_revised_proposal=None,
        discussion_next_action=None,
        discussion_review_stance=None,
        idea_canvas=None,
        application_form_items=application_form_items or [],
    )


def apply_user_answer(previous_state: IdeationConvState, answer_message: ConvMessage) -> IdeationConvState:
    """awaiting_planning_answer 또는 awaiting_developer_answer 상태에 사용자 답변
    메시지를 추가하고, 다음에 실행할 노드를 가리키는 phase로 전환한다.

    다음 phase 결정: 이 함수를 부르기 전 상태(phase)만으로 결정되며 LLM 판단을
    거치지 않는다 — "사용자가 답하지 않은 내용을 임의로 확정하지 않는다"는 요구와
    별개로, 애초에 다음에 어느 전문가 차례인지는 사용자 판단이 개입할 여지가 없는
    고정 순서(기획 질문 -> 개발 질문 -> 두 전문가 보완)이기 때문이다.
    """
    prev_phase = previous_state["phase"]
    next_phase: ConvPhase
    if prev_phase == "awaiting_candidate_selection":
        # 용준/Claude(2026-07-21): discovery 모드 — 사용자가 후보 선택/결합/재추천/전문가
        # 추천 중 하나로 답했다. 실제 해석(번호 선택인지, 결합인지, 재추천인지)은 이
        # 함수가 하지 않는다 — candidate_selection 노드가 담당한다(요청: 단순 선택은
        # 코드로 결정적으로, 자연어 결합/수정은 LLM으로).
        next_phase = "candidate_selection"
    elif prev_phase == "awaiting_planning_answer":
        next_phase = "developer_question"
    elif prev_phase == "awaiting_developer_answer":
        next_phase = "expert_discussion"
    elif prev_phase == "awaiting_user_decision":
        # 요청 8번 "필요한 경우 추가 질문 라운드" — 시스템이 스스로 판단해 다음 라운드로
        # 넘어가는 경우(next_action="continue_round")와 별개로, 사용자가 확정 버튼을
        # 누르지 않고 자유롭게 한 마디 더 남기면 그 발언도 두 전문가의 보완 의견 대상이
        # 된다. round는 새로 늘리지 않는다 — 새 질문 사이클이 시작된 게 아니라 같은
        # 라운드의 대화가 이어지는 것이기 때문이다.
        next_phase = "expert_discussion"
    else:
        raise ValueError(f"사용자 답변을 받을 수 없는 phase입니다: {prev_phase!r}")

    return IdeationConvState(
        **{
            **previous_state,
            "messages": previous_state["messages"] + [answer_message],
            "phase": next_phase,
            "pending_question": None,
            "pending_expected_answer_type": None,
            "pending_question_topic": None,
            # 다음 단계로 실제로 넘어가는 시점이므로 재질문 카운터를 리셋한다(새 쟁점 시작).
            "answer_retry_count": 0,
        }
    )


def request_finalize(previous_state: IdeationConvState) -> IdeationConvState:
    """사용자가 '주제 확정하고 초안 받기'를 눌렀을 때만 호출된다(요구 9~10번 —
    전문가/진행자가 임의로 최종 확정하지 않는다). phase="awaiting_user_decision"이 아니면
    호출부(API)가 이 함수를 부르기 전에 이미 막아야 한다."""
    if previous_state["phase"] != "awaiting_user_decision":
        raise ValueError(
            f"awaiting_user_decision 상태에서만 최종 확정할 수 있습니다(현재: {previous_state['phase']!r})."
        )
    return IdeationConvState(**{**previous_state, "phase": "finalizing"})


def is_graph_entry_phase(phase: str) -> bool:
    """그래프가 이 phase로 새로 진입해 노드를 실행해도 되는지 여부.
    awaiting_*/finalized/failed/awaiting_user_decision은 API가 그래프를 다시 부르지
    않고 사용자 입력을 기다려야 하는 지점이다."""
    return phase in _TERMINAL_ENTRY_PHASES or phase == "finalizing"
