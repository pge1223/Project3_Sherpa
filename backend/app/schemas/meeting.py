from typing import Optional

from pydantic import BaseModel


# 가은/Claude(2026-07-16): STEP4 "공모전 분석" 화면(멘토 추천/선택) 신규 스키마.
# 후보 풀은 rubric_mapping_{domain}.json의 committee(도메인당 4명 고정)를 그대로 쓴다 —
# LLM은 새 인물을 만들지 않고, 이미 정해진 후보에 대해 fit_tag(왜 이 문서에 어울리는지)만
# 붙인다.
class MentorCandidate(BaseModel):
    persona_id: str
    display_name: str
    role: str
    fit_tag: str


class MentorCandidatesResponse(BaseModel):
    characteristics: list[str]
    candidates: list[MentorCandidate]


# committee가 없으면(기존 호출 호환) rubric_mapping의 전체 committee를 그대로 쓴다.
# progress_token: 프론트가 POST 전에 미리 만들어 보내는 임의 문자열(예: crypto.randomUUID()).
# analyze()가 동기 응답이라 완료 전까지 meeting_id를 알 수 없는데, 진행률 폴링
# (GET /{project_id}/analyze/progress)은 그 전에 시작해야 해서 프론트가 먼저 토큰을
# 발급해 넘긴다. 안 보내면(기존 호출 호환) 진행률 기록을 아예 안 한다.
class AnalyzeRequest(BaseModel):
    committee: Optional[list[str]] = None
    progress_token: Optional[str] = None


class AnalyzeProgress(BaseModel):
    stage: Optional[str] = None
    reviews_done: int = 0
    reviews_total: int = 0
    score_done: bool = False
    chair_done: bool = False


# 가은/Claude(2026-07-17): STEP7 "대화형 피드백" 화면 — 저장된 회의 결과(직전 analyze()의
# reviewer_results/chair_summary)를 근거로 후속 질문에 답한다. 개별 위원 재평가
# (reevaluate_reviewer, 전체 재채점)와 달리 이건 짧은 Q&A라 훨씬 가볍다 — 별도 채점/저장
# 없이 answer 텍스트만 돌려준다.
class AskQuestionRequest(BaseModel):
    question: str
    # 프론트가 세션 동안 주고받은 이전 질문/답변을 그대로 넘긴다(서버는 대화 기록을
    # 저장하지 않음 — 매 요청이 stateless, 문맥은 매번 프론트가 채워서 보낸다).
    history: Optional[list[dict]] = None


# 가은/Claude(2026-07-17): 사용자가 매번 "어느 위원에게 물어볼지" 고르지 않아도 되게,
# 질문 내용을 보고 라우팅(_build_routing_prompt)해서 관련 위원 1~3명 또는 위원장이
# 자동으로 답한다 — 그래서 응답이 화자 1명 고정이 아니라 목록이다.
class AskAnswer(BaseModel):
    persona_id: str
    display_name: str
    answer: str


class AskQuestionResponse(BaseModel):
    answers: list[AskAnswer]
