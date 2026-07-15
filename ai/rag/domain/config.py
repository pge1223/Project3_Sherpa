"""
Shared Domain Constants
========================
embedding/과 retrieval/이 함께 참조하는 상수만 둔다 (레이어 역전 방지: 다른 모듈이
domain을 참조하는 것은 되지만, domain이 embedding/retrieval을 참조하지는 않는다).
"""

DEFAULT_COLLECTION_NAME: str = "project_documents_kure_v1"

# Chroma 컬렉션 이름 규칙 (chromadb 실제 검증 메시지 기준: 3~512자, [a-zA-Z0-9._-], 시작/끝은 영숫자)
COLLECTION_NAME_PATTERN: str = r"^[a-zA-Z0-9][a-zA-Z0-9._-]{1,510}[a-zA-Z0-9]$"
