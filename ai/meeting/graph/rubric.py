# 작성자: 경이
# 목적: ai/meeting/personas/rubric_mapping_*.json(가은 PER-002 산출물)을 review_output.schema.json
#       v2의 rubric 객체와, 위원 라우팅 정보(어느 criterion을 어느 persona가 채점하는지)로
#       변환한다(M4). 도메인 무관하게 동작한다 — government_support/competition 매핑 모두
#       같은 persona_rubric_mapping 스키마를 쓰기 때문이다.
# import: 표준 라이브러리 typing만 사용.

from __future__ import annotations

from typing import Any


def build_rubric(mapping: dict[str, Any]) -> dict[str, Any]:
    """rubric_mapping_*.json의 rubric[] 배열을 v2 rubric 객체로 변환한다.

    default_supplementary_perspectives는 채점 대상이 아니므로 포함하지 않는다.
    """
    criteria = [
        {
            "criterion_id": item["criterion_id"],
            "criterion_name": item["criterion_name"],
            "max_score": item["max_score"],
            "required": item["required"],
        }
        for item in mapping["rubric"]
    ]
    domain = mapping["meta"]["domain"]
    return {
        "rubric_id": f"RUBRIC-{domain.upper()}",
        "source_document_id": None,
        "total_max_score": mapping["total_max_score"],
        "criteria": criteria,
    }


def build_routing(mapping: dict[str, Any]) -> dict[str, dict[str, str | None]]:
    """criterion_id -> {"primary": persona_id, "secondary": persona_id 또는 None} 매핑을 만든다.

    노드/그래프 조립이 "이 기준은 누가 채점하는가"를 알아야 할 때 쓴다(현재 reviewer
    노드는 위원 전체가 rubric 전체를 보고 자기 전문 범위만 채점하므로 라우팅을 강제하진
    않지만, 배정 근거를 추적하거나 향후 위원별 rubric 부분집합을 넘길 때 재사용한다).
    """
    return {
        item["criterion_id"]: {
            "primary": item["primary_persona_id"],
            "secondary": item.get("secondary_persona_id"),
        }
        for item in mapping["rubric"]
    }
