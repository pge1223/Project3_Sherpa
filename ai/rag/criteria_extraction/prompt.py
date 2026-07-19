"""
LLM 프롬프트 조립.
"""

from __future__ import annotations

from ai.rag.chunking.schemas import Chunk

_INSTRUCTIONS = """\
너는 공고문(사업 공모/지원사업 모집요강)에서 평가기준(심사기준)을 추출하는 보조자다.
아래는 공고문에서 평가기준일 가능성이 높은 구간만 추린 발췌문이다. 각 발췌문 앞에는
[chunk_id=... page=...] 형태의 출처 표시가 붙어 있다.

규칙:
1. 실제 평가기준(심사항목)만 추출한다. 접수 방법, 제출 서류, 문의처 등 평가기준이
   아닌 내용은 제외한다.
2. 배점(숫자)이 원문에 명시되어 있지 않으면 weight를 반드시 null로 남긴다. 절대
   배점을 추측하거나 다른 항목에서 유추해 채우지 않는다.
3. source_text에는 근거가 된 원문 문장을 그대로(요약하지 말고) 인용한다.
4. source_chunk_id에는 그 항목의 근거가 된 발췌문의 chunk_id를 정확히 그대로 적는다.
5. 같은 평가항목이 여러 발췌문에 걸쳐 반복되면 하나로 합쳐 한 번만 반환한다.
6. 평가기준을 하나도 찾지 못하면 criteria를 빈 배열로 반환한다.

다음 JSON 형식으로만 응답한다(설명 문장, 마크다운 코드블록 없이 JSON만):
{
  "criteria": [
    {
      "criterion_id": "영문 snake_case 짧은 식별자",
      "name": "평가항목 이름",
      "description": "평가항목에 대한 설명",
      "weight": 숫자 또는 null,
      "source_text": "원문 인용",
      "source_chunk_id": "위 발췌문의 chunk_id"
    }
  ]
}

발췌문:
"""


def build_extraction_prompt(candidates: list[Chunk]) -> str:
    """후보 청크 목록으로 LLM 프롬프트를 만든다.

    candidates는 반드시 1개 이상이어야 한다 — 없으면 호출자(서비스 계층)가 애초에
    LLM을 호출하지 않아야 한다.
    """
    if not candidates:
        raise ValueError("candidates가 비어 있으면 프롬프트를 만들 수 없습니다")

    blocks = []
    for chunk in candidates:
        page_label = chunk.location_number if chunk.location_number is not None else "unknown"
        blocks.append(f"[chunk_id={chunk.chunk_id} page={page_label}]\n{chunk.content}")

    return _INSTRUCTIONS + "\n\n".join(blocks)
