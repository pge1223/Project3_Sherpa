# 작성자: 경이
# 목적: ai/meeting/graph 패키지 공개 인터페이스. State/그래프 조립/rubric 변환/실행
#       엔트리포인트를 노출한다.
# import: 같은 패키지의 state, build, rubric, run, llm.

from .build import assemble_meeting_graph
from .llm import make_openai_llm_call
from .reevaluate import assemble_reevaluation_graph, reevaluation_state
from .rerun import rerun_reviewer
from .rubric import build_dynamic_rubric_mapping, build_rubric, build_routing
from .run import run_chair_phase, run_meeting
from .state import MeetingState, MeetingStage, initial_state

# 용준/Claude(2026-07-20): "아이디어 발전 회의(ideation)" 모드 — 기존 심사형 회의(위 import들)와
# 완전히 분리된 병렬 서브시스템. 기존 export는 하나도 건드리지 않았다.
from .ideation_build import assemble_ideation_graph
from .ideation_run import continue_ideation_meeting, start_ideation_meeting
from .ideation_state import IdeationStage, IdeationState, initial_ideation_state, resume_ideation_state

# 용준/Claude(2026-07-20): "아이디어 발전 회의(ideation)" 대화형(conversational) 개발용
# 프리뷰 — 배치형(위 ideation_* import들)과 완전히 분리된 병렬 서브시스템. 사용자가 질문
# 하나마다 답하며 진행하는 구조라 State/그래프/실행부가 모두 별도 파일(ideation_conv_*)이다.
from .ideation_conv_build import assemble_ideation_conversation_graph
from .ideation_conv_run import (
    finalize_ideation_conversation,
    reply_ideation_conversation,
    start_ideation_conversation,
)
from .ideation_conv_state import (
    ROADMAP_PREREQUISITE_TOPICS,
    TOPIC_PRIORITY,
    ConvPhase,
    IdeationConvState,
    active_stage_for,
    initial_conv_state,
    remaining_topics_for,
)

__all__ = [
    "MeetingState",
    "MeetingStage",
    "assemble_meeting_graph",
    "assemble_reevaluation_graph",
    "reevaluation_state",
    "build_dynamic_rubric_mapping",
    "build_routing",
    "build_rubric",
    "initial_state",
    "make_openai_llm_call",
    "rerun_reviewer",
    "run_chair_phase",
    "run_meeting",
    "IdeationState",
    "IdeationStage",
    "assemble_ideation_graph",
    "continue_ideation_meeting",
    "initial_ideation_state",
    "resume_ideation_state",
    "start_ideation_meeting",
    "IdeationConvState",
    "ConvPhase",
    "active_stage_for",
    "remaining_topics_for",
    "TOPIC_PRIORITY",
    "ROADMAP_PREREQUISITE_TOPICS",
    "assemble_ideation_conversation_graph",
    "initial_conv_state",
    "start_ideation_conversation",
    "reply_ideation_conversation",
    "finalize_ideation_conversation",
]
