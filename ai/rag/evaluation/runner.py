"""
Retrieval Evaluation Runner
==============================
평가셋(EvaluationDataset)의 각 케이스를 RoleAwareRetrievalService(또는 같은
Protocol을 만족하는 fake)로 검색하고 metrics.py의 순수 함수로 지표를 계산한다.

- 색인/삭제는 절대 수행하지 않는다 (읽기 전용 검색만).
- backend, ai.meeting을 import하지 않는다.
- 실제 KURE/Chroma 조립은 이 파일 하단의 CLI(main) 안에서만 지연 import로
  수행한다 — RetrievalEvaluationRunner 자체는 chromadb/sentence-transformers
  없이도 단위 테스트가 가능하다.

CLI 실행 예:
    python -m ai.rag.evaluation.runner \\
        --dataset path/to/retrieval_golden.json \\
        --chroma-path backend/chroma_db \\
        --k 1 3 5 \\
        --output reports/rag_retrieval_baseline.json
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Protocol, Sequence

from ai.rag.evaluation.metrics import (
    deduplicate_ranked_ids,
    hit_rate_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from ai.rag.evaluation.schemas import (
    AggregateMetrics,
    CaseMetrics,
    EvaluationCase,
    EvaluationDataset,
    EvaluationReport,
    RetrievalSettingsSnapshot,
)
from ai.rag.role_retrieval.schemas import RoleSearchResponse

DEFAULT_K_VALUES: tuple[int, ...] = (1, 3, 5)


class RoleSearchRetriever(Protocol):
    """RoleAwareRetrievalService.search_by_role()과 동일한 시그니처.

    실제 서비스와 테스트용 FakeRetriever 모두 이 Protocol만 만족하면 되므로,
    Runner는 어느 쪽이 주입됐는지 알 필요가 없다(구조적 서브타이핑).
    """

    def search_by_role(
        self,
        query: str,
        project_id: str,
        role_id: Optional[str] = None,
        document_id: Optional[str] = None,
        top_k: int = 5,
        candidate_k: Optional[int] = None,
    ) -> RoleSearchResponse: ...


def default_settings_snapshot(k_values: Sequence[int]) -> RetrievalSettingsSnapshot:
    """chunking/role_retrieval 기본 설정에서 baseline 설정값을 읽어온다.

    여러 파일에 chunk_size=800 같은 값을 다시 하드코딩하지 않기 위해, 실제
    설정 소스(ai.rag.chunking.config, ai.rag.role_retrieval.config)에서 읽는다.
    """
    from ai.rag.chunking.config import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE
    from ai.rag.role_retrieval.config import RoleRerankConfig

    rerank_defaults = RoleRerankConfig()
    return RetrievalSettingsSnapshot(
        chunk_size=DEFAULT_CHUNK_SIZE,
        chunk_overlap=DEFAULT_CHUNK_OVERLAP,
        semantic_weight=rerank_defaults.semantic_weight,
        role_weight=rerank_defaults.role_weight,
        candidate_k_multiplier=rerank_defaults.candidate_k_multiplier,
        k_values=list(k_values),
    )


def _evaluate_case(case: EvaluationCase, response: RoleSearchResponse, k_values: Sequence[int]) -> CaseMetrics:
    ranked_ids = deduplicate_ranked_ids([result.chunk_id for result in response.results])
    relevant_ids = set(case.relevant_chunk_ids)

    return CaseMetrics(
        case_id=case.case_id,
        project_id=case.project_id,
        domain=case.domain,
        persona_id=case.persona_id,
        role_id=case.role_id,
        criterion_id=case.criterion_id,
        query=case.query,
        retrieved_chunk_ids=ranked_ids,
        relevant_chunk_ids=sorted(relevant_ids),
        reciprocal_rank=reciprocal_rank(ranked_ids, relevant_ids),
        precision_at_k={k: precision_at_k(ranked_ids, relevant_ids, k) for k in k_values},
        recall_at_k={k: recall_at_k(ranked_ids, relevant_ids, k) for k in k_values},
        hit_rate_at_k={k: hit_rate_at_k(ranked_ids, relevant_ids, k) for k in k_values},
        ndcg_at_k={k: ndcg_at_k(ranked_ids, relevant_ids, k) for k in k_values},
        result_count=len(ranked_ids),
        warnings=list(response.warnings),
    )


def _aggregate(case_metrics: list[CaseMetrics], k_values: Sequence[int]) -> AggregateMetrics:
    case_count = len(case_metrics)

    def _mean(values: list[float]) -> float:
        return sum(values) / case_count if case_count else 0.0

    return AggregateMetrics(
        mean_precision_at_k={k: _mean([c.precision_at_k[k] for c in case_metrics]) for k in k_values},
        mean_recall_at_k={k: _mean([c.recall_at_k[k] for c in case_metrics]) for k in k_values},
        mean_hit_rate_at_k={k: _mean([c.hit_rate_at_k[k] for c in case_metrics]) for k in k_values},
        mean_ndcg_at_k={k: _mean([c.ndcg_at_k[k] for c in case_metrics]) for k in k_values},
        mrr=_mean([c.reciprocal_rank for c in case_metrics]),
        case_count=case_count,
        empty_result_case_count=sum(1 for c in case_metrics if c.result_count == 0),
    )


class RetrievalEvaluationRunner:
    """평가셋을 검색 서비스(RoleSearchRetriever)로 실행하고 지표를 계산한다."""

    def __init__(
        self,
        retriever: RoleSearchRetriever,
        k_values: Sequence[int] = DEFAULT_K_VALUES,
        settings: Optional[RetrievalSettingsSnapshot] = None,
    ):
        if not k_values:
            raise ValueError("k_values는 최소 1개 이상이어야 합니다")
        for k in k_values:
            if k < 1:
                raise ValueError(f"k_values의 모든 값은 1 이상이어야 합니다: {k}")

        self._retriever = retriever
        self._k_values: tuple[int, ...] = tuple(sorted(set(k_values)))
        self._settings = settings

    def run(
        self,
        dataset: EvaluationDataset,
        run_id: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> EvaluationReport:
        max_k = max(self._k_values)
        case_metrics: list[CaseMetrics] = []
        for case in dataset.cases:
            response = self._retriever.search_by_role(
                query=case.query,
                project_id=case.project_id,
                role_id=case.role_id,
                top_k=max_k,
            )
            case_metrics.append(_evaluate_case(case, response, self._k_values))

        return EvaluationReport(
            dataset_name=dataset.dataset_name,
            dataset_version=dataset.version,
            run_id=run_id or str(uuid.uuid4()),
            executed_at=datetime.now(timezone.utc),
            settings=self._settings or default_settings_snapshot(self._k_values),
            case_metrics=case_metrics,
            aggregate=_aggregate(case_metrics, self._k_values),
            notes=notes,
        )


def _build_real_retriever(chroma_path: str, collection_name: str) -> tuple[RoleSearchRetriever, RetrievalSettingsSnapshot]:
    """실제 KURE/Chroma를 조립한다. CLI에서만 호출되며, 색인/삭제는 하지 않고
    이미 색인된 Chroma 데이터를 읽기 전용으로 검색만 한다.

    backend.app.api.routes.documents._get_indexing_service()(private 함수)는
    사용하지 않고, ai.rag가 공개하는 클래스만으로 독립 조립한다.
    """
    from ai.rag.chunking.config import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE
    from ai.rag.embedding import KUREEmbedder
    from ai.rag.embedding.config import EMBEDDING_VERSION
    from ai.rag.retrieval import ChromaVectorStore, RAGIndexingService, create_persistent_client
    from ai.rag.role_retrieval.config import RoleRerankConfig
    from ai.rag.role_retrieval.service import RoleAwareRetrievalService

    embedder = KUREEmbedder()
    client = create_persistent_client(path=chroma_path)
    store = ChromaVectorStore(
        client=client,
        collection_name=collection_name,
        embedding_model=embedder.model_name,
        embedding_dimension=embedder.embedding_dimension,
        embedding_version=EMBEDDING_VERSION,
    )
    indexing_service = RAGIndexingService(embedder, store)
    role_retrieval_service = RoleAwareRetrievalService(retrieval_service=indexing_service)

    rerank_defaults = RoleRerankConfig()
    settings = RetrievalSettingsSnapshot(
        chunk_size=DEFAULT_CHUNK_SIZE,
        chunk_overlap=DEFAULT_CHUNK_OVERLAP,
        semantic_weight=rerank_defaults.semantic_weight,
        role_weight=rerank_defaults.role_weight,
        candidate_k_multiplier=rerank_defaults.candidate_k_multiplier,
        k_values=[],  # runner가 실제 k_values로 덮어써서 다시 생성한다
        embedding_model=embedder.model_name,
        embedding_version=EMBEDDING_VERSION,
        collection_name=collection_name,
    )
    return role_retrieval_service, settings


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    from ai.rag.domain.config import DEFAULT_COLLECTION_NAME

    parser = argparse.ArgumentParser(
        description="RAG-003 역할 기반 검색 오프라인 평가 실행기 (읽기 전용, 색인/삭제 없음)",
    )
    parser.add_argument("--dataset", required=True, help="평가셋 JSON 경로")
    parser.add_argument("--chroma-path", required=True, help="이미 색인된 Chroma persist 디렉터리 경로")
    parser.add_argument(
        "--collection-name",
        default=DEFAULT_COLLECTION_NAME,
        help=f"Chroma 컬렉션 이름 (기본값: {DEFAULT_COLLECTION_NAME})",
    )
    parser.add_argument("--k", type=int, nargs="+", default=list(DEFAULT_K_VALUES), help="K 값 목록 (기본값: 1 3 5)")
    parser.add_argument("--output", required=True, help="결과 리포트 JSON 저장 경로")
    parser.add_argument("--run-id", default=None, help="실행 식별자 (미지정 시 uuid4로 생성)")
    parser.add_argument("--notes", default=None, help="리포트에 남길 메모 (예: 실험 이름)")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> EvaluationReport:
    args = _parse_args(argv)

    from ai.rag.evaluation.dataset import load_dataset

    dataset = load_dataset(args.dataset)
    retriever, settings = _build_real_retriever(args.chroma_path, args.collection_name)
    settings.k_values = sorted(set(args.k))

    runner = RetrievalEvaluationRunner(retriever=retriever, k_values=args.k, settings=settings)
    report = runner.run(dataset, run_id=args.run_id, notes=args.notes)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(json.loads(report.model_dump_json()), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"평가 리포트 저장됨: {output_path}")
    print(f"MRR={report.aggregate.mrr:.4f} case_count={report.aggregate.case_count} "
          f"empty_result_case_count={report.aggregate.empty_result_case_count}")
    return report


if __name__ == "__main__":
    main()
