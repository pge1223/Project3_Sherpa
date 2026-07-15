"""
Chroma Metadata Sanitization
==============================
EmbeddedChunk.metadata(원시 dict)를 Chroma가 실제로 받아들이는 형태로 변환하고,
검색 결과에서 다시 원래 타입으로 복원한다.

실제 설치된 chromadb(1.5.9)로 직접 확인한 제약:
  - 허용 값 타입: str, int, float, bool
  - None 값을 가진 키를 넣으면 조용히 버려짐 (validate_metadata는 통과하지만 저장 안 됨) →
    혼동을 피하기 위해 우리가 먼저 명시적으로 제거한다.
  - 비어 있지 않은 list[str]/list[int]는 실제로 저장/왕복이 되지만, 빈 list([])는
    'Expected metadata list value ... to be non-empty' ValueError로 즉시 거부된다.
    source_block_ids/source_block_orders는 웹 문서 기원 청크에서 항상 빈 리스트일 수 있어
    (ai.rag.chunking.schemas.Chunk 독스트링 참고) 리스트 길이에 따라 저장 형태가 갈리면
    검색측 로직이 복잡해지고, 향후 다른 chromadb 버전/HttpClient 배포에서 리스트 지원
    여부가 달라질 수도 있으므로, 길이와 무관하게 항상 JSON 문자열로 직렬화해 저장한다.
"""

import json
from enum import Enum

# JSON 문자열로 직렬화해서 저장하고, 검색 결과에서 다시 list로 복원할 필드
_JSON_LIST_FIELDS: frozenset[str] = frozenset({"source_block_ids", "source_block_orders"})


def sanitize_metadata_for_chroma(raw_metadata: dict) -> dict:
    """
    None 값 제거, Enum → value(str), list 필드 → JSON 문자열.
    이미 str/int/float/bool인 값은 그대로 둔다.
    """
    sanitized: dict = {}
    for key, value in raw_metadata.items():
        if value is None:
            continue
        if isinstance(value, Enum):
            sanitized[key] = value.value
            continue
        if key in _JSON_LIST_FIELDS:
            sanitized[key] = json.dumps(value, ensure_ascii=False)
            continue
        if isinstance(value, (str, int, float, bool)):
            sanitized[key] = value
            continue
        # 예상 밖의 복합 타입(dict 등)이 섞여 들어오면 JSON 문자열로 안전하게 변환
        sanitized[key] = json.dumps(value, ensure_ascii=False)
    return sanitized


def restore_metadata(chroma_metadata: dict) -> dict:
    """sanitize_metadata_for_chroma()의 역변환. JSON 리스트 필드를 list로 복원한다."""
    restored: dict = dict(chroma_metadata)
    for key in _JSON_LIST_FIELDS:
        if key in restored and isinstance(restored[key], str):
            restored[key] = json.loads(restored[key])
    return restored
