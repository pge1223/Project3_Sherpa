"""
RAG Retrieval Offline Evaluation
====================================
RAG-003 역할 기반 검색(RoleAwareRetrievalService)의 품질을 사람이 만든 정답
(chunk_id) 평가셋 기준으로 Recall@K, Precision@K, Hit Rate@K, MRR, nDCG@K로
정량 측정한다. 청킹 크기·재랭킹 가중치·top_k 등을 바꿔가며 같은 평가셋으로
비교(A/B)할 수 있도록 실행 설정을 결과 리포트에 함께 기록한다.

이 패키지는 backend, ai.meeting을 import하지 않는다 — ai.rag 하위 공개
API(KUREEmbedder, ChromaVectorStore, RAGIndexingService,
RoleAwareRetrievalService)만 사용해 독립적으로 동작한다.

사용 예시:
    from ai.rag.evaluation import load_dataset, RetrievalEvaluationRunner

    dataset = load_dataset("path/to/retrieval_golden.json")
    runner = RetrievalEvaluationRunner(retriever=role_retrieval_service, k_values=[1, 3, 5])
    report = runner.run(dataset)
"""

from ai.rag.evaluation.dataset import load_dataset
from ai.rag.evaluation.runner import RetrievalEvaluationRunner, RoleSearchRetriever, default_settings_snapshot
from ai.rag.evaluation.schemas import (
    AggregateMetrics,
    CaseMetrics,
    EvaluationCase,
    EvaluationDataset,
    EvaluationReport,
    RetrievalSettingsSnapshot,
)

__all__ = [
    "load_dataset",
    "RetrievalEvaluationRunner",
    "RoleSearchRetriever",
    "default_settings_snapshot",
    "AggregateMetrics",
    "CaseMetrics",
    "EvaluationCase",
    "EvaluationDataset",
    "EvaluationReport",
    "RetrievalSettingsSnapshot",
]
