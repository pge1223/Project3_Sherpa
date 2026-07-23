"""
Ideation Target Evidence Indexing Service
===============================================
용준/Claude(2026-07-22, 요청: 선택된 아이디어/사용자 답변을 target evidence로 색인).

아이디어 회의(ideation-conversation)에서 (a) 사용자가 선택/결합한 아이디어 후보, (b) 회의
중 사용자가 구체적으로 제공한 답변을 실제 target evidence로 만들어 기존 문서 색인 파이프라인
(청킹 -> 임베딩 -> Chroma upsert, ai/rag/retrieval/service.py::RAGIndexingService)에 그대로
태운다. 새 collection이나 새 벡터DB를 만들지 않고, 기존 project_documents_kure_v1 collection에
document_role="target"으로 색인한다.

파일 파싱(ai/rag/parsers)은 건너뛴다 — 원본이 PDF/DOCX가 아니라 이미 구조화된 텍스트(후보
dict 필드, 사용자 답변 원문)이므로, DocumentExtractionResult를 프로그램이 직접 조립해
chunk_document()부터 재사용한다(청킹 이후 단계는 일반 문서 업로드와 완전히 동일한 코드 경로).

중복 인덱싱 방지: 결정적 document_id를 쓴다 —
- 후보: f"ideation-target::{project_id}::{session_id}::{candidate_id}"
- 사용자 답변: f"ideation-answer::{project_id}::{session_id}::{user_message_id}"
같은 document_id로 다시 호출하면 RAGIndexingService.index_chunking_result()가 이미
upsert(추가 아님) + stale record 삭제를 수행하므로(ai/rag/retrieval/chroma_store.py), 내용이
바뀌지 않았으면 같은 chunk_id 집합이 그대로 덮어써지고, 내용이 바뀌면 새 chunk_id 집합으로
교체되며 이전 chunk는 자동으로 삭제된다 — 별도의 버전/해시 추적 로직을 새로 만들 필요가 없다.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

from ai.rag.chunking.chunker import chunk_document
from ai.rag.chunking.schemas import ChunkSourceContext, SourceType
from ai.rag.domain.schemas import IndexingContext
from ai.rag.parsers.schemas import BlockType, DocumentBlock, DocumentExtractionResult, FileType, LocationType
from ai.rag.retrieval.service import RAGIndexingService

logger = logging.getLogger(__name__)

IDEATION_SOURCE_TYPE_CANDIDATE = "ideation_candidate"
IDEATION_SOURCE_TYPE_USER_ANSWER = "user_session_answer"


class IdeationTargetIndexingError(Exception):
    """target evidence 색인이 실패했을 때(청킹/임베딩/Chroma 저장 중 어떤 단계든) 던진다.
    호출부(ai/meeting에 주입되는 콜러블 — backend/app/api/routes/ideation_conversation_preview.py)
    가 이 예외를 잡아 로그만 남기고 회의 자체는 중단시키지 않아야 한다(요청: "인덱싱 실패를
    조용히 무시하지 말되, 이미 저장된 회의 state가 손상되면 안 됨")."""


@dataclass
class IdeationTargetIndexResult:
    document_id: str
    chunk_count: int
    content_hash: str
    elapsed_ms: float


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _build_extraction_result(*, document_id: str, sections: list[tuple[str, str]]) -> DocumentExtractionResult:
    """sections=[(제목, 본문), ...]를 DocumentBlock 목록으로 변환한다. 페이지 개념이 없는
    합성 텍스트라 DOCX와 같은 취급(LocationType.DOCUMENT)을 쓴다 — 실제 DOCX 파일을
    업로드했다는 뜻이 아니라, chunk_document()의 어댑터(ai/rag/chunking/adapters.py::
    _FILE_TYPE_TO_LOCATION_TYPE)가 "페이지 번호 없는 문서" 취급을 이미 DOCX로 지원하기
    때문이다(PDF 전용 분기를 타지 않도록 새 FileType을 만들지 않고 그대로 재사용한다).
    빈 본문은 블록을 만들지 않는다(억지로 색인 대상을 만들지 않는다)."""
    blocks = [
        DocumentBlock(
            block_id=f"{document_id}::block-{idx}",
            block_type=BlockType.TEXT,
            content=f"{title}\n{body}".strip() if title else body.strip(),
            location_type=LocationType.DOCUMENT,
            location_number=None,
            order=idx,
        )
        for idx, (title, body) in enumerate(sections)
        if body and body.strip()
    ]
    return DocumentExtractionResult(
        document_id=document_id,
        file_name=document_id,
        file_type=FileType.DOCX,
        file_size=sum(len(b.content) for b in blocks),
        block_count=len(blocks),
        blocks=blocks,
    )


def _index_sections(
    *,
    indexing_service: RAGIndexingService,
    project_id: str,
    document_id: str,
    document_title: str,
    sections: list[tuple[str, str]],
    extra_metadata: dict[str, Any],
) -> IdeationTargetIndexResult:
    started = time.perf_counter()
    extraction = _build_extraction_result(document_id=document_id, sections=sections)
    if not extraction.blocks:
        raise IdeationTargetIndexingError(f"색인할 본문이 비어 있습니다(document_id={document_id!r})")

    full_content = "\n\n".join(block.content for block in extraction.blocks)
    content_hash = _content_hash(full_content)

    chunk_context = ChunkSourceContext(
        document_id=document_id, source_type=SourceType.IDEATION_GENERATED, source_filename=document_title
    )
    chunking_result = chunk_document(extraction, chunk_context)
    indexing_context = IndexingContext(
        project_id=project_id,
        document_id=document_id,
        document_title=document_title,
        document_role="target",
        extra_metadata={**extra_metadata, "content_hash": content_hash},
    )
    try:
        summary = indexing_service.index_chunking_result_with_summary(chunking_result, indexing_context)
    except Exception as exc:  # noqa: BLE001 — 호출부가 실패를 로그로 남기고 안전 진행해야 한다.
        raise IdeationTargetIndexingError(
            f"target evidence 색인 실패(document_id={document_id!r}): {exc}"
        ) from exc

    return IdeationTargetIndexResult(
        document_id=document_id,
        chunk_count=summary.stored_count,
        content_hash=content_hash,
        elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
    )


def _candidate_sections(candidate: dict) -> list[tuple[str, str]]:
    """선택된 후보 dict(ai/meeting/graph/ideation_conv_discovery.py가 만드는 candidate 형태 —
    title/problem/target_user/solution/main_features/differentiation/required_data/
    technical_approach/mvp_scope 등)를 사람이 읽는 섹션 텍스트로 변환한다. LLM을 다시 호출하지
    않는다 — 이미 확정된 후보 필드를 그대로 옮겨 적을 뿐이라 사실 왜곡 위험이 없다."""

    def _join(value: Any) -> str:
        if isinstance(value, list):
            return "\n".join(f"- {v}" for v in value if v)
        return str(value or "")

    return [
        ("제목:", str(candidate.get("title") or "")),
        ("문제:", _join(candidate.get("problem"))),
        ("대상 사용자:", _join(candidate.get("target_user"))),
        ("해결 방식:", _join(candidate.get("solution"))),
        ("주요 기능:", _join(candidate.get("main_features"))),
        ("차별점:", _join(candidate.get("differentiation"))),
        ("기대 효과:", _join(candidate.get("core_value"))),
        ("필요 데이터:", _join(candidate.get("required_data"))),
        ("기술 접근 방식:", _join(candidate.get("technical_approach"))),
        ("MVP 범위:", _join(candidate.get("mvp_scope"))),
        ("현재까지 확인된 제약사항:", _join(candidate.get("risks"))),
    ]


def index_selected_candidate_as_target(
    *,
    indexing_service: RAGIndexingService,
    project_id: str,
    session_id: str,
    candidate_id: str,
    candidate: dict,
) -> IdeationTargetIndexResult:
    """사용자가 선택/결합한 아이디어 후보 1건을 target evidence로 색인한다. document_id는
    (project_id, session_id, candidate_id)로 결정적이라, 같은 후보를 다시 선택하거나 /reply가
    재시도돼도 같은 문서를 upsert할 뿐 중복 생성되지 않는다."""
    document_id = f"ideation-target::{project_id}::{session_id}::{candidate_id}"
    document_title = f"[선택한 아이디어] {candidate.get('title') or candidate_id}"
    return _index_sections(
        indexing_service=indexing_service,
        project_id=project_id,
        document_id=document_id,
        document_title=document_title,
        sections=_candidate_sections(candidate),
        extra_metadata={
            "ideation_source_type": IDEATION_SOURCE_TYPE_CANDIDATE,
            "session_id": session_id,
            "candidate_id": candidate_id,
        },
    )


def index_user_answer_as_target(
    *,
    indexing_service: RAGIndexingService,
    project_id: str,
    session_id: str,
    user_message_id: str,
    answer_text: str,
    pending_question: Optional[str] = None,
    pending_question_topic: Optional[str] = None,
) -> IdeationTargetIndexResult:
    """회의 중 사용자가 제공한 답변 1건을 target evidence로 색인한다. 요청 17-1번(사용자 답변
    원문 보존) — LLM으로 "데이터 제공기관"/"분석 주기" 같은 구조화 필드를 추출해서 저장하지
    않는다. 검증된 결정적 파서가 없으므로, 사용자가 실제로 말한 원문과 그 답이 어떤 질문에
    대한 것이었는지(pending_question/pending_question_topic)만 그대로 보존한다 — 이 자체가
    "사용자가 확정한 사실"이며, 왜곡 없이 그대로 검색 근거가 된다.

    document_id는 (project_id, session_id, user_message_id)로 결정적이라, 같은 사용자 메시지가
    재시도/재전송돼도 중복 색인되지 않는다(요청 4번 "같은 답변이 재처리돼도 중복 청크 생성
    안 됨" + 요청 17-9번 "같은 user_message_id가 중복 인덱싱되지 않아야 함")."""
    document_id = f"ideation-answer::{project_id}::{session_id}::{user_message_id}"
    sections: list[tuple[str, str]] = []
    if pending_question:
        sections.append(("질문:", pending_question))
    sections.append(("사용자 답변:", answer_text))
    return _index_sections(
        indexing_service=indexing_service,
        project_id=project_id,
        document_id=document_id,
        document_title="[사용자 추가 답변] 회의 답변",
        sections=sections,
        extra_metadata={
            "ideation_source_type": IDEATION_SOURCE_TYPE_USER_ANSWER,
            "session_id": session_id,
            "user_message_id": user_message_id,
            "pending_question_topic": pending_question_topic or "",
        },
    )


__all__ = [
    "IDEATION_SOURCE_TYPE_CANDIDATE",
    "IDEATION_SOURCE_TYPE_USER_ANSWER",
    "IdeationTargetIndexingError",
    "IdeationTargetIndexResult",
    "index_selected_candidate_as_target",
    "index_user_answer_as_target",
]
