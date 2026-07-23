"""
Ideation Target Evidence Indexing Service Tests
=====================================================
용준/Claude(2026-07-22, 요청: 선택된 아이디어/사용자 답변을 target evidence로 색인).
실제 OpenAI/Chroma에 의존하지 않는다 — indexing_service를 duck-typed fake로 주입해
청킹 결과(ChunkingResult)와 IndexingContext가 실제로 무엇을 담아 넘겨지는지만 검증한다.
"""

import pytest

from ai.rag.orchestration.ideation_target_indexing_service import (
    IDEATION_SOURCE_TYPE_CANDIDATE,
    IDEATION_SOURCE_TYPE_USER_ANSWER,
    IdeationTargetIndexingError,
    index_selected_candidate_as_target,
    index_user_answer_as_target,
)

CANDIDATE = {
    "title": "스마트 에너지 관리 플랫폼",
    "problem": "에너지 낭비와 관리 비효율로 의사결정이 늦어진다.",
    "target_user": "주거 단지 관리자, 도시 에너지 운영자",
    "solution": "스마트 미터링 데이터를 수집해 AI로 소비 패턴을 분석한다.",
    "main_features": ["실시간 모니터링", "이상 사용량 감지"],
    "differentiation": "사용자 맞춤형 절약 팁 제공",
}


class _FakeSummary:
    def __init__(self, stored_count: int):
        self.stored_count = stored_count


class _FakeIndexingService:
    """RAGIndexingService.index_chunking_result_with_summary와 동일한 시그니처만 흉내 낸다."""

    def __init__(self):
        self.calls: list[tuple] = []

    def index_chunking_result_with_summary(self, chunking_result, context):
        self.calls.append((chunking_result, context))
        return _FakeSummary(len(chunking_result.chunks))


class _FailingIndexingService:
    def index_chunking_result_with_summary(self, chunking_result, context):
        raise RuntimeError("chroma 저장 실패(테스트 시뮬레이션)")


# ---------------------------------------------------------------------------
# 1. candidate 선택 시 target evidence 생성
# ---------------------------------------------------------------------------


def test_selected_candidate_indexed_with_target_role_and_candidate_source_type():
    svc = _FakeIndexingService()
    result = index_selected_candidate_as_target(
        indexing_service=svc, project_id="P1", session_id="S1", candidate_id="candidate_1", candidate=CANDIDATE
    )
    assert result.document_id == "ideation-target::P1::S1::candidate_1"
    assert result.chunk_count >= 1

    _, context = svc.calls[0]
    assert context.document_role == "target"
    assert context.extra_metadata["ideation_source_type"] == IDEATION_SOURCE_TYPE_CANDIDATE
    assert context.extra_metadata["session_id"] == "S1"
    assert context.extra_metadata["candidate_id"] == "candidate_1"


def test_selected_candidate_reindex_with_same_content_is_idempotent():
    """중복 인덱싱 방지 — 같은 후보를 다시 선택해도 같은 document_id/chunk_id 집합으로
    upsert될 뿐, 새 문서가 생기지 않는다."""
    svc = _FakeIndexingService()
    r1 = index_selected_candidate_as_target(
        indexing_service=svc, project_id="P1", session_id="S1", candidate_id="candidate_1", candidate=CANDIDATE
    )
    r2 = index_selected_candidate_as_target(
        indexing_service=svc, project_id="P1", session_id="S1", candidate_id="candidate_1", candidate=CANDIDATE
    )
    assert r1.document_id == r2.document_id
    ids1 = [c.chunk_id for c in svc.calls[0][0].chunks]
    ids2 = [c.chunk_id for c in svc.calls[1][0].chunks]
    assert ids1 == ids2
    assert r1.content_hash == r2.content_hash


def test_selected_candidate_reindex_after_content_change_uses_same_document_id_new_chunks():
    svc = _FakeIndexingService()
    r1 = index_selected_candidate_as_target(
        indexing_service=svc, project_id="P1", session_id="S1", candidate_id="candidate_1", candidate=CANDIDATE
    )
    changed = dict(CANDIDATE, solution="완전히 다른 해결 방식으로 변경되었습니다.")
    r2 = index_selected_candidate_as_target(
        indexing_service=svc, project_id="P1", session_id="S1", candidate_id="candidate_1", candidate=changed
    )
    assert r1.document_id == r2.document_id  # 같은 document_id — upsert 대상.
    assert r1.content_hash != r2.content_hash
    ids1 = [c.chunk_id for c in svc.calls[0][0].chunks]
    ids2 = [c.chunk_id for c in svc.calls[1][0].chunks]
    assert ids1 != ids2  # 새 chunk_id 집합 — 기존 upsert 로직이 이전 chunk를 stale로 정리한다.


def test_indexing_failure_raises_ideation_target_indexing_error():
    with pytest.raises(IdeationTargetIndexingError):
        index_selected_candidate_as_target(
            indexing_service=_FailingIndexingService(),
            project_id="P1",
            session_id="S1",
            candidate_id="candidate_1",
            candidate=CANDIDATE,
        )


# ---------------------------------------------------------------------------
# 2. 사용자 답변 시 session target evidence 생성
# ---------------------------------------------------------------------------


def test_user_answer_indexed_with_target_role_and_user_answer_source_type():
    svc = _FakeIndexingService()
    result = index_user_answer_as_target(
        indexing_service=svc,
        project_id="P1",
        session_id="S1",
        user_message_id="MSG-1",
        answer_text="한국전력 API와 아파트 스마트 미터 데이터를 사용하고 5분 단위로 분석하려고 합니다.",
        pending_question="어떤 데이터를 쓸 계획인가요?",
        pending_question_topic="data",
    )
    assert result.document_id == "ideation-answer::P1::S1::MSG-1"
    _, context = svc.calls[0]
    assert context.document_role == "target"
    assert context.extra_metadata["ideation_source_type"] == IDEATION_SOURCE_TYPE_USER_ANSWER
    assert context.extra_metadata["session_id"] == "S1"
    assert context.extra_metadata["user_message_id"] == "MSG-1"


def test_user_answer_preserves_raw_text_without_llm_restructuring():
    """요청 17-1번 — LLM으로 "데이터 제공기관"/"분석 주기" 등을 추출해 저장하지 않고, 사용자
    원문을 그대로 청크 본문에 담는다(색인 함수 자체가 LLM을 호출하지 않는다)."""
    svc = _FakeIndexingService()
    raw_answer = "한국전력 API와 아파트 스마트 미터 데이터를 사용하고 5분 단위로 분석하려고 합니다."
    index_user_answer_as_target(
        indexing_service=svc,
        project_id="P1",
        session_id="S1",
        user_message_id="MSG-1",
        answer_text=raw_answer,
    )
    chunking_result, _ = svc.calls[0]
    full_text = "\n".join(c.content for c in chunking_result.chunks)
    assert raw_answer in full_text


# ---------------------------------------------------------------------------
# 3. 같은 답변 재처리 — 중복 청크 생성 안 됨
# ---------------------------------------------------------------------------


def test_same_user_answer_reprocessed_does_not_create_duplicate_chunks():
    svc = _FakeIndexingService()
    kwargs = dict(
        indexing_service=svc,
        project_id="P1",
        session_id="S1",
        user_message_id="MSG-1",
        answer_text="한국전력 API와 아파트 스마트 미터 데이터를 사용하고 5분 단위로 분석하려고 합니다.",
    )
    r1 = index_user_answer_as_target(**kwargs)
    r2 = index_user_answer_as_target(**kwargs)
    assert r1.document_id == r2.document_id
    ids1 = [c.chunk_id for c in svc.calls[0][0].chunks]
    ids2 = [c.chunk_id for c in svc.calls[1][0].chunks]
    assert ids1 == ids2  # 같은 document_id·같은 chunk_id로 upsert될 뿐 새 청크가 생기지 않는다.


def test_different_user_message_ids_produce_different_documents():
    svc = _FakeIndexingService()
    r1 = index_user_answer_as_target(
        indexing_service=svc, project_id="P1", session_id="S1", user_message_id="MSG-1", answer_text="답변 1"
    )
    r2 = index_user_answer_as_target(
        indexing_service=svc, project_id="P1", session_id="S1", user_message_id="MSG-2", answer_text="답변 2"
    )
    assert r1.document_id != r2.document_id
