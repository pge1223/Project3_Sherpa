# 작성자: 경이
# 목적: 개인 맞춤형 피드백 루프(버전 추적형 User RAG)의 "개발 위원 피드백 개인화" 로직.
#       사용자 프로필(전공 여부·학위·경력·GitHub 통계)로 개발 지적(미해결/신규)의 구현
#       난이도를 결정론으로 판정하고(classify_impl_difficulty), 그 판정에 맞춰 상세도가
#       다른 구현 가이드를 만든다(build_impl_guide). 난이도 판정 자체는 LLM이 아니라 규칙
#       으로만 계산해 재현성을 보장하고(점수 엔진과 같은 철학), 가이드 산문(prose)만 선택적
#       으로 주입된 llm_call로 생성한다 — llm_call이 없으면 산문 없이 판정/상세도만 돌려줘
#       테스트·폴백이 가능하다(run_meeting과 동일한 DI 패턴). 회의 파이프라인/프롬프트를
#       건드리지 않는 "후처리(B안)"라 프로필이 없으면 자연 폴백된다.
#       프론트 실험 화면 VersionTrackerTestPage.jsx 의 IMPL_GUIDE mock을 대체할 실로직.
# import: 표준 라이브러리 typing/json만 사용.

from __future__ import annotations

from typing import Any, Callable

# 구현 난이도 가이드를 붙일 "기술/개발 위원" persona_id.
# 회의 위원회에는 committee:'dev' 같은 플래그가 없고 도메인별 4인 persona가 들어간다
# (competition: creativity_originality/technical_feasibility/business_strategy/presentation_completeness,
#  government_support: policy_fit/business_strategy/technical_feasibility/budget_execution).
# 이 중 "기술·구현·운영 관점"을 맡는 위원이 technical_feasibility 이며, 그의 지적이 곧
# "구현해야 할 일"이다 — 개인화(구현 난이도) 가이드는 이 위원 지적에만 붙인다. dev_expert는
# 아이디어 발전 회의(ideation) 쪽 개발 전문가라 함께 화이트리스트에 둔다. 기획/사업/완성도
# 위원 지적엔 붙이지 않는다.
TECHNICAL_PERSONA_IDS = frozenset({"technical_feasibility", "dev_expert"})


def is_technical_persona(persona_id: str | None) -> bool:
    """이 persona가 구현 난이도 가이드를 붙일 기술/개발 위원인지 판단한다.
    backend가 reviewer_results에서 개발 위원 지적만 골라 attach_impl_guides로 넘길 때 쓴다."""
    return persona_id in TECHNICAL_PERSONA_IDS

# 구현 난이도 3단계와 그에 맞춘 설명 상세도.
# hard  = 비전공/무경험 → 길고 친절한 단계별(detailed)
# moderate = 어느 정도 기술 배경 → 표준(standard)
# easy  = 전공+경력 → 짧고 간결(brief)
_VERBOSITY_BY_LEVEL = {"hard": "detailed", "moderate": "standard", "easy": "brief"}
_LABEL_BY_LEVEL = {
    "hard": "구현 난이도 · 어려울 수 있음",
    "moderate": "구현 난이도 · 보통",
    "easy": "구현 난이도 · 쉬움",
}


def _competence_signals(profile: dict[str, Any]) -> list[tuple[str, int]]:
    """프로필에서 (근거 문구, 가중치) 목록을 뽑는다. 가중치 합이 클수록 기술 역량이 높다.

    각 신호는 마이페이지에서 사용자가 제출하는 값(전공/학위/경력/GitHub 통계)에서만
    나온다 — 값이 없으면(키 누락) 0으로 취급해, GitHub·이력을 안 낸 사용자도 안전하게
    동작한다(그 경우 신호가 적어 hard로 수렴).
    """
    education = profile.get("education") or {}
    experience = profile.get("experience") or {}
    github = profile.get("github") or {}

    signals: list[tuple[str, int]] = []
    if education.get("is_technical_major"):
        signals.append(("기술 계열 전공", 2))
    if str(education.get("degree")) in {"master", "phd"}:
        signals.append(("석사 이상 학위", 1))
    if (experience.get("it_internship_months") or 0) >= 3:
        signals.append(("IT 실무(인턴) 경력", 1))
    if (experience.get("competition_participations") or 0) >= 1:
        signals.append(("이전 공모전 참여 경험", 1))
    if github.get("has_backend_experience"):
        signals.append(("GitHub 백엔드 이력", 1))
    if (github.get("relevant_projects") or 0) >= 1:
        signals.append(("관련(RAG/AI) 프로젝트 이력", 1))
    if (github.get("total_commits") or 0) >= 200:
        signals.append(("활발한 GitHub 활동", 1))
    return signals


def classify_impl_difficulty(profile: dict[str, Any] | None) -> dict[str, Any] | None:
    """사용자 프로필로 개발 지적의 구현 난이도를 결정론으로 판정한다.

    프로필이 없으면(마이페이지 미제출) None을 돌려준다 — 개인화를 붙이지 않고 기존 회의
    피드백 그대로 보여주라는 신호다.

    반환: {"level": "hard"|"moderate"|"easy", "score": int, "verbosity": str,
           "label": str, "signals": [근거 문구...]}
    """
    if not profile:
        return None
    signals = _competence_signals(profile)
    score = sum(w for _, w in signals)
    if score >= 5:
        level = "easy"
    elif score >= 2:
        level = "moderate"
    else:
        level = "hard"
    return {
        "level": level,
        "score": score,
        "verbosity": _VERBOSITY_BY_LEVEL[level],
        "label": _LABEL_BY_LEVEL[level],
        "signals": [text for text, _ in signals],
    }


# 상세도별 가이드 생성 지시. 판정은 결정론이지만 "가이드 산문"은 지적마다 달라서 LLM으로
# 생성한다(선택). 상세도에 따라 길이·단계 유무를 다르게 지시한다.
_VERBOSITY_INSTRUCTION = {
    "detailed": (
        "이 사용자는 비전공자/입문자입니다. 전문 용어를 풀어 설명하고, 무엇을 왜 하는지와 "
        "①②③ 형태의 단계별 실행 방법을 5~7문장으로 친절하게 안내하세요."
    ),
    "standard": (
        "이 사용자는 어느 정도 기술 배경이 있습니다. 핵심 실행 방법을 2~3문장으로 간결하되 "
        "구체적으로 안내하세요."
    ),
    "brief": (
        "이 사용자는 전공+실무 경력이 있습니다. 스택·명령·파라미터 위주로 1~2문장의 아주 "
        "간결한 요약만 주세요(입문 설명 금지)."
    ),
}


def build_impl_guide_prompt(feedback: dict[str, Any], classification: dict[str, Any]) -> str:
    """개발 지적 1건 + 난이도 판정으로 '구현 가이드'를 생성하라는 LLM 프롬프트를 만든다.
    지적의 text/suggestion을 벗어난 새로운 요구를 지어내지 말라고 강제한다(회의 결과 grounding).
    """
    text = feedback.get("text", "")
    suggestion = feedback.get("suggestion", "")
    instruction = _VERBOSITY_INSTRUCTION[classification["verbosity"]]
    return f"""당신은 IT 공모전 개발 위원의 지적을, 제출자의 기술 수준에 맞춰 "어떻게 구현할지"
안내하는 보조입니다. 아래 지적 범위 안에서만 설명하고, 지적에 없는 새로운 요구를 만들지 마세요.

[제출자 기술 수준]
{instruction}

[개발 위원 지적]
{text}

[권고 방향(있으면 참고)]
{suggestion or "(없음)"}

다음 JSON 형식으로만 응답하세요:
{{"guide": "..."}}"""


def build_impl_guide(
    feedback: dict[str, Any],
    profile: dict[str, Any] | None,
    llm_call: Callable[[str], str] | None = None,
) -> dict[str, Any] | None:
    """개발 지적 1건에 프로필 기반 구현 난이도/가이드를 붙인다.

    - 프로필이 없으면 None(개인화 없음).
    - llm_call이 없으면 판정(level/verbosity/label/signals)만 담고 prose=None으로 돌려준다
      (테스트·폴백). 있으면 build_impl_guide_prompt로 가이드 산문을 생성해 prose에 채운다.
    - 이미 해결된 지적(status == "resolved")은 구현할 게 없으므로 None을 돌려준다.
    """
    if not profile:
        return None
    if feedback.get("status") == "resolved":
        return None
    classification = classify_impl_difficulty(profile)
    if classification is None:
        return None

    prose: str | None = None
    if llm_call is not None:
        import json

        raw = llm_call(build_impl_guide_prompt(feedback, classification))
        try:
            prose = (json.loads(raw) or {}).get("guide")
        except (json.JSONDecodeError, TypeError):
            prose = None

    return {
        "feedback_id": feedback.get("id"),
        "level": classification["level"],
        "verbosity": classification["verbosity"],
        "label": classification["label"],
        "prose": prose,
    }


def attach_impl_guides(
    dev_feedback: list[dict[str, Any]],
    profile: dict[str, Any] | None,
    llm_call: Callable[[str], str] | None = None,
) -> list[dict[str, Any]]:
    """개발 위원의 지적 목록에 구현 가이드를 매핑한다(해결된 항목은 건너뛰어 None 제외).
    dev_feedback은 개발 위원(committee) 소속 지적만 넘겨받는다고 가정한다 — 어떤 지적이
    개발 위원 것인지 고르는 라우팅은 호출부(backend) 몫이다(담당 경계)."""
    guides: list[dict[str, Any]] = []
    for f in dev_feedback:
        guide = build_impl_guide(f, profile, llm_call)
        if guide is not None:
            guides.append(guide)
    return guides
