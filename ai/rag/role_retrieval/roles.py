"""
Role Profile Registry
========================
지원하는 심사위원 역할을 이 모듈 하나에서만 관리한다. 서비스/검색 계층은
role_id로 이 레지스트리를 조회할 뿐, 역할 정의를 직접 알지 못한다 — 역할을
추가/수정할 때는 이 파일(또는 커스텀 RoleRegistry 생성 시 넘기는 목록)만 바꾸면 된다.
"""

from ai.rag.role_retrieval.schemas import RoleProfile

_FINANCE = RoleProfile(
    role_id="finance",
    display_name="재무 심사위원",
    description="예산, 비용, 매출, 수익성, 자금조달 등 재무 관점에서 사업계획서를 검토한다.",
    query_instruction=(
        "재무 심사 관점에서 예산, 비용, 매출, 수익성, 자금조달 및 재무 위험과 "
        "관련된 근거를 우선 검색하세요."
    ),
    focus_keywords=[
        "예산", "비용", "매출", "수익성", "자금조달", "손익", "재무 위험",
        "투자", "원가", "현금흐름", "수익", "재무",
    ],
    section_keywords=["예산", "비용", "재무", "자금", "손익", "수익"],
)

_TECHNOLOGY = RoleProfile(
    role_id="technology",
    display_name="기술 심사위원",
    description="기술 구조, 구현 가능성, 성능, 보안, 확장성 관점에서 사업계획서를 검토한다.",
    query_instruction=(
        "기술 심사 관점에서 기술 구조, 구현 가능성, 성능, 보안, 확장성 및 "
        "기술 위험과 관련된 근거를 우선 검색하세요."
    ),
    focus_keywords=[
        "기술 구조", "구현", "성능", "보안", "확장성", "기술 위험", "아키텍처",
        "알고리즘", "인프라", "기술",
    ],
    section_keywords=["기술", "시스템", "아키텍처", "구현", "개발"],
)

_MARKETING = RoleProfile(
    role_id="marketing",
    display_name="마케팅 심사위원",
    description="목표 고객, 시장 규모, 경쟁사, 차별성 등 마케팅 관점에서 사업계획서를 검토한다.",
    query_instruction=(
        "마케팅 심사 관점에서 목표 고객, 시장 규모, 경쟁사, 차별성, 홍보 및 "
        "고객 확보와 관련된 근거를 우선 검색하세요."
    ),
    focus_keywords=[
        "목표 고객", "시장 규모", "경쟁사", "차별성", "홍보", "고객 확보",
        "마케팅", "브랜드", "시장",
    ],
    section_keywords=["시장", "고객", "마케팅", "경쟁", "홍보"],
)

_PLANNING = RoleProfile(
    role_id="planning",
    display_name="기획·사업 심사위원",
    description="문제 정의, 목표, 사업 모델, 일정, 인력, 운영 등 기획·사업 관점에서 사업계획서를 검토한다.",
    query_instruction=(
        "기획·사업 심사 관점에서 문제 정의, 목표, 사업 모델, 일정, 인력, 운영 "
        "및 리스크와 관련된 근거를 우선 검색하세요."
    ),
    focus_keywords=[
        "문제 정의", "목표", "사업 모델", "일정", "인력", "운영", "리스크",
        "전략", "비즈니스 모델", "계획",
    ],
    section_keywords=["개요", "목표", "일정", "운영", "계획", "전략"],
)

_POLICY = RoleProfile(
    role_id="policy",
    display_name="정책·공공성 심사위원",
    description=(
        "정책 목표, 공공성, 지원요건, 규정, 사회적 가치 및 정책 부합성 관점에서 "
        "사업계획서를 검토한다."
    ),
    query_instruction=(
        "정책·공공성 심사 관점에서 정책 목표, 정책 부합성, 공공성, 지원요건·지원대상, "
        "규정 및 준수사항, 사회적 가치, 지역·산업 정책 연계, 지원 종료 후 지속가능성, "
        "성과지표와 관련된 근거를 우선 검색하세요."
    ),
    focus_keywords=[
        "정책 목표", "정책 부합성", "공공성", "지원요건", "지원대상", "규정", "준수사항",
        "사회적 가치", "지역 연계", "산업 정책", "지속가능성", "성과지표",
    ],
    section_keywords=["정책", "공공성", "지원요건", "지원대상", "사회적 가치", "성과지표"],
)

_BUDGET_EXECUTION = RoleProfile(
    role_id="budget_execution",
    display_name="예산·집행계획 심사위원",
    description=(
        "예산 편성, 사업비 집행, 산출 근거, 일정, 마일스톤, 정산 및 위험 대응 관점에서 "
        "사업계획서를 검토한다."
    ),
    query_instruction=(
        "예산·집행계획 심사 관점에서 예산 및 사업비, 예산 배분, 비용 산출 근거, 집행계획, "
        "보조금 및 자부담, 추진 일정, 마일스톤, 정산 및 보고, 위험 대응 및 예비비, "
        "성과와 예산의 연결과 관련된 근거를 우선 검색하세요."
    ),
    focus_keywords=[
        "예산", "사업비", "예산 배분", "비용 산출 근거", "집행계획", "자부담", "보조금",
        "추진 일정", "마일스톤", "정산", "위험 대응", "예비비",
    ],
    section_keywords=["예산", "사업비", "집행계획", "일정", "마일스톤", "정산"],
)

DEFAULT_ROLE_PROFILES: dict[str, RoleProfile] = {
    profile.role_id: profile
    for profile in (_FINANCE, _TECHNOLOGY, _MARKETING, _PLANNING, _POLICY, _BUDGET_EXECUTION)
}


class UnsupportedRoleError(ValueError):
    """지원하지 않는 role_id를 조회했을 때 발생"""


class RoleRegistry:
    """role_id -> RoleProfile 조회를 담당하는 레지스트리. 기본값은 DEFAULT_ROLE_PROFILES."""

    def __init__(self, profiles: dict[str, RoleProfile] | None = None):
        self._profiles: dict[str, RoleProfile] = dict(profiles) if profiles is not None else dict(DEFAULT_ROLE_PROFILES)

    def get(self, role_id: str) -> RoleProfile:
        try:
            return self._profiles[role_id]
        except KeyError:
            supported = ", ".join(sorted(self._profiles))
            raise UnsupportedRoleError(
                f"지원하지 않는 role_id입니다: {role_id!r} (지원 목록: {supported})"
            ) from None

    def has(self, role_id: str) -> bool:
        return role_id in self._profiles

    def list_roles(self) -> list[RoleProfile]:
        return list(self._profiles.values())
