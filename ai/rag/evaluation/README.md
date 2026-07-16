# RAG 검색 오프라인 평가 (RAG-003 Retrieval Evaluation)

`RoleAwareRetrievalService`(RAG-003 역할 기반 검색)의 검색 품질을 사람이 만든
정답(chunk_id) 평가셋 기준으로 **Recall@K, Precision@K, Hit Rate@K, MRR, nDCG@K**로
정량 측정하는 오프라인 평가 하네스입니다. 청킹 크기, 재랭킹 가중치
(`semantic_weight`/`role_weight`), `top_k` 등을 바꿔가며 **같은 평가셋**으로
결과를 비교(A/B)할 수 있도록, 실행 시점의 설정값을 결과 리포트에 함께 기록합니다.

이 패키지는 `backend`, `ai.meeting`을 import하지 않습니다. `ai.rag` 하위 공개
API(`KUREEmbedder`, `ChromaVectorStore`, `RAGIndexingService`,
`RoleAwareRetrievalService`)만 사용해 독립적으로 동작하며, **색인·수정·삭제는
절대 수행하지 않고 이미 색인된 Chroma 데이터를 읽기 전용으로 검색만 합니다.**

## 디렉터리 구조

```
ai/rag/evaluation/
├── __init__.py          # 공개 API 재노출
├── schemas.py            # 평가셋 입력 스키마 + 결과 리포트 출력 스키마 (pydantic)
├── dataset.py            # JSON -> EvaluationDataset 로더
├── metrics.py             # 외부 의존성 없는 순수 지표 함수
├── runner.py              # DI 기반 평가 실행기 + CLI(`python -m ai.rag.evaluation.runner`)
├── examples/
│   └── retrieval_golden.example.json   # 형식 예시 (SAMPLE — 실제 정답 아님)
└── README.md
```

테스트는 `ai/rag/tests/test_evaluation_dataset.py`,
`test_evaluation_metrics.py`, `test_evaluation_runner.py`에 있습니다.

## 지표 정의

`ranked_ids`는 검색 결과를 점수순으로 나열한 chunk_id 리스트(중복은 최초
등장 순위만 유지), `relevant_ids`는 사람이 표시한 정답 chunk_id 집합입니다.

- **Precision@K** = 상위 K개 중 관련 청크 수 / **실제 반환된** 상위 K개 수
  (검색 결과가 K개 미만이면 분모는 실제 개수입니다. 결과가 0개면 0.)
- **Recall@K** = 상위 K개에서 찾은 관련 청크 수 / 전체 정답 청크 수
- **Hit Rate@K** = 상위 K개에 정답 청크가 하나라도 있으면 1, 없으면 0
- **Reciprocal Rank** = 첫 번째 정답 청크가 나온 순위(1-indexed)의 역수.
  정답이 하나도 없으면 0.
- **MRR** = 전체 케이스 Reciprocal Rank의 평균 (aggregate 단계에서 계산)
- **nDCG@K** = binary relevance 기준 `DCG@K / IDCG@K`.
  `DCG@K = Σ rel_i / log2(rank_i + 1)` (관련이면 rel=1, 아니면 0),
  `IDCG@K`는 정답이 이상적으로 상위에 모두 몰려 있을 때의 DCG(정답 수와 K 중
  작은 값만큼 1이 앞에 옴).

경계 조건:
- 검색 결과가 없으면 모든 지표는 0입니다.
- `relevant_chunk_ids`가 비어 있는 케이스는 애초에 스키마 validation에서 막힙니다
  (`EvaluationCase`가 최소 1개를 요구).
- 반환 결과에 같은 `chunk_id`가 중복되면 최초 순위만 유지합니다
  (`metrics.deduplicate_ranked_ids`).
- `k`가 1 미만이면 `ValueError`가 발생합니다.
- 0으로 나누는 경우(정답 0개, 결과 0개 등)는 모두 사전에 처리되어 예외 없이 0을 반환합니다.

## 평가셋 스키마

```json
{
  "dataset_name": "competition_retrieval_v1",
  "version": "1.0.0",
  "cases": [
    {
      "case_id": "competition-001",
      "project_id": "PROJECT_ID",
      "domain": "competition",
      "persona_id": "business_strategy",
      "role_id": "finance",
      "criterion_id": "contribution",
      "query": "사업성과 시장 기여도",
      "relevant_chunk_ids": ["CHUNK_ID_1", "CHUNK_ID_2"],
      "expected_sufficiency": "sufficient",
      "notes": "정답 청크는 사람이 직접 확인해 입력"
    }
  ]
}
```

검증 규칙 (`ai/rag/evaluation/schemas.py`):

- `case_id`, `project_id`, `domain`, `persona_id`, `role_id`, `query`는 빈 문자열 불가
- `relevant_chunk_ids`는 최소 1개 이상, 중복 시 validation error
- 같은 `case_id`가 데이터셋 안에서 중복되면 validation error
- `domain`/`persona_id`/`role_id`(/`criterion_id`) 조합은 **조용히 허용되지 않습니다** —
  `ai.rag.orchestration.role_mapping.resolve_role_id()`(RAG-003이 실제로 쓰는
  매핑)를 그대로 재사용해 검증하므로, `role_id`가 실제 매핑 결과와 다르거나
  `domain`/`persona_id`가 아직 매핑되지 않은 조합(예: `government_support`)이면
  `PersonaRoleMappingError`가 그대로 `ValidationError`로 올라옵니다. 새 조합이
  필요하면 평가셋이 아니라 `role_mapping.py`를 먼저 팀과 상의해 업데이트하세요.
- `expected_sufficiency`, `notes`는 optional. `expected_sufficiency`는 RAG-005
  (충분성 평가) 연계를 위해 예약된 필드로, 이번 RAG-003 평가에서는 사용하지 않습니다.

## 평가셋을 사람이 만드는 방법

1. **평가 대상 프로젝트 선정**: 이미 Chroma에 색인된(`project_id`가 존재하는)
   사업계획서/기획서를 하나 고릅니다.
2. **위원 관점별 질의 설계**: 도메인(`competition`)의 4개 역할
   (`finance`/`technology`/`marketing`/`planning`)과 대응하는 persona_id
   (`business_strategy`/`technical_feasibility`/`creativity_originality`/
   `presentation_completeness`)에 대해, 실제 위원이 던질 법한 질의를 작성합니다.
3. **Chroma의 chunk_id와 PDF 페이지를 확인해 정답을 표시하는 방법**:
   - 색인된 Chroma persist 디렉터리를 열어 해당 `project_id`의 레코드를 조회합니다
     (`record_id`는 `f"{project_id}::{chunk_id}"` 형식 — `ai.rag.retrieval.chroma_store.build_record_id`
     참고). 예:
     ```python
     from ai.rag.retrieval import create_persistent_client

     client = create_persistent_client(path="backend/chroma_db")
     collection = client.get_collection("project_documents_kure_v1")
     records = collection.get(
         where={"project_id": "PROJECT_ID"},
         include=["documents", "metadatas"],
     )
     for record_id, content, metadata in zip(records["ids"], records["documents"], records["metadatas"]):
         print(record_id, metadata.get("chunk_id"), metadata.get("page_number"), content[:80])
     ```
   - 위 목록에서 질의와 실제로 관련 있는 chunk를 사람이 직접 읽고 판단합니다.
     `metadata`에 페이지 번호/섹션 제목이 들어있다면 원본 PDF의 해당 페이지를
     열어 내용이 실제로 질의에 답하는지 확인하세요.
   - 확인된 `chunk_id`(레코드의 `chunk_id` 메타데이터 값, `record_id` 전체가
     아님)를 `relevant_chunk_ids`에 추가합니다.
4. **실제 정답을 임의로 만들면 안 되는 이유**: 이 하네스가 측정하는 것은
   "검색기가 사람이 실제로 관련 있다고 판단한 근거를 찾아내는가"입니다.
   chunk_id를 추측하거나 임의로 지어내면 지표가 실제 검색 품질과 무관한
   난수가 되어, 청킹/가중치/`top_k`를 바꿨을 때의 비교가 전부 무의미해집니다.
   또한 잘못된 정답으로 소급 검증한 "개선"은 실제 사용자에게는 오히려
   품질 저하로 나타날 수 있습니다. 이 저장소에는 **형식을 보여주는
   `examples/retrieval_golden.example.json`(SAMPLE)만** 포함되어 있으며, 실제
   평가셋은 이 파일을 참고해 별도로 작성해야 합니다.

## Baseline 실행 방법

```bash
python -m ai.rag.evaluation.runner \
  --dataset path/to/retrieval_golden.json \
  --chroma-path backend/chroma_db \
  --k 1 3 5 \
  --output reports/rag_retrieval_baseline.json
```

- `--chroma-path`는 **이미 색인이 끝난** Chroma persist 디렉터리를 가리켜야
  합니다. 이 명령은 검색만 수행하며 색인/삭제는 하지 않습니다.
- `--collection-name`을 생략하면 `ai.rag.domain.config.DEFAULT_COLLECTION_NAME`
  (`project_documents_kure_v1`)을 사용합니다.
- 내부적으로 `KUREEmbedder`, `ChromaVectorStore`, `RAGIndexingService`,
  `RoleAwareRetrievalService`를 CLI 안에서 직접 조립합니다(`backend`의
  private 함수 `_get_indexing_service()`는 사용하지 않습니다). 실제 KURE 모델을
  로드하므로 최초 실행은 다소 시간이 걸릴 수 있습니다.
- 라이브러리(`RetrievalEvaluationRunner`, `load_dataset`)와 CLI 조립 로직을
  같은 `runner.py` 파일에 두되, 실제 서비스 조립(`_build_real_retriever`)과
  argparse 진입점(`main`)은 함수 내부에서 `chromadb`/`sentence-transformers`를
  **지연 import**합니다. 그 결과 `RetrievalEvaluationRunner` 자체를 사용하는
  단위 테스트는 무거운 실제 의존성을 전혀 로드하지 않고 fake retriever만으로
  실행됩니다. CLI를 완전히 별도 파일로 분리하는 대신 이 방식을 택한 이유는,
  요청된 실행 명령(`python -m ai.rag.evaluation.runner ...`)을 그대로 지원하면서도
  라이브러리 코드와 조립 코드의 관심사를 지연 import로 충분히 분리할 수 있기
  때문입니다.

## 결과 JSON 해석 방법

```json
{
  "dataset_name": "competition_retrieval_v1",
  "dataset_version": "1.0.0",
  "run_id": "…",
  "executed_at": "2026-07-17T00:00:00+00:00",
  "settings": {
    "chunk_size": 800,
    "chunk_overlap": 120,
    "semantic_weight": 0.75,
    "role_weight": 0.25,
    "candidate_k_multiplier": 3,
    "k_values": [1, 3, 5],
    "embedding_model": "nlpai-lab/KURE-v1",
    "embedding_version": "embedding_v1",
    "collection_name": "project_documents_kure_v1"
  },
  "case_metrics": [ { "case_id": "…", "precision_at_k": {"1": 1.0, "3": 0.67, "5": 0.4}, "…": "…" } ],
  "aggregate": {
    "mean_precision_at_k": {"1": 0.8, "3": 0.6, "5": 0.5},
    "mean_recall_at_k": {"1": 0.3, "3": 0.7, "5": 0.9},
    "mean_hit_rate_at_k": {"1": 0.8, "3": 0.95, "5": 1.0},
    "mean_ndcg_at_k": {"1": 0.8, "3": 0.72, "5": 0.75},
    "mrr": 0.74,
    "case_count": 20,
    "empty_result_case_count": 0
  }
}
```

- `settings`는 **이번 실행에 실제로 쓰인 설정값**입니다. 청킹 크기나
  `semantic_weight`/`role_weight`/`candidate_k_multiplier`를 바꿔 재실행하면
  이 값이 그대로 바뀌어 기록되므로, 리포트만 봐도 어떤 설정으로 나온 결과인지
  알 수 있습니다.
- `case_metrics`는 케이스별 상세(검색된 순위, 케이스별 지표)이고,
  `aggregate`는 전체 평균입니다. `empty_result_case_count`가 0보다 크면
  일부 케이스가 검색 결과를 전혀 얻지 못했다는 뜻이므로 우선 원인(잘못된
  `project_id`, role_id 매핑 오류 등)을 확인하세요.

## 설정 변경 전후 비교 방법

1. baseline을 먼저 실행해 `reports/rag_retrieval_baseline.json`을 만듭니다.
2. 튜닝하려는 값(청킹 크기, `RoleRerankConfig.semantic_weight`/`role_weight`,
   `top_k` 등)만 바꾼 뒤, **같은 `--dataset`**으로 다시 실행해 다른 출력 경로
   (예: `reports/rag_retrieval_experiment_a.json`)에 저장합니다.
3. 두 리포트의 `settings`가 실제로 의도한 값만 다른지 먼저 확인한 다음,
   `aggregate.mean_recall_at_k`/`mean_precision_at_k`/`mrr`/`mean_ndcg_at_k`를
   나란히 비교합니다. `case_metrics` 단위로 비교하면 어떤 케이스가 개선/악화됐는지
   구체적으로 파악할 수 있습니다.
4. 청킹 크기처럼 재색인이 필요한 변경은 별도 Chroma 컬렉션/디렉터리에
   재색인한 뒤 `--chroma-path`/`--collection-name`을 그 경로로 지정해
   실행해야 baseline과 공정하게 비교됩니다.

## 지표 해석 예시

- **Recall은 높은데 Precision이 낮다**: `top_k`(또는 `candidate_k_multiplier`)가
  너무 커서 관련 없는 청크까지 상위권에 많이 섞여 있다는 뜻입니다. 위원에게
  보여줄 근거 개수를 줄이거나 재랭킹 가중치를 조정해 상위권 순도를 높이는 게
  우선입니다.
- **Precision은 높은데 Recall이 낮다**: 검색기가 자신 있는 소수의 청크만
  찾고, 관련된 다른 청크는 놓치고 있다는 뜻입니다. `top_k`를 늘리거나
  청킹 크기를 조정해 관련 정보가 더 잘게/다르게 나뉘어 있는지 살펴보세요.
- **Hit Rate@K는 높은데 nDCG@K가 낮다**: 정답이 상위 K 안에 있긴 하지만
  순위가 낮다는 뜻입니다(예: 5위 안에는 있지만 5위 자체). 재랭킹
  가중치(`semantic_weight` vs `role_weight`)를 조정해 정답의 순위를
  끌어올리는 방향을 검토하세요.
- **MRR이 낮다**: 여러 케이스에서 첫 정답이 늦게 나온다는 뜻이므로, 위원이
  "가장 먼저 보는 근거"의 품질에 문제가 있을 가능성이 큽니다.

## 사람이 직접 준비해야 하는 데이터

- 실제 평가셋 JSON(이 저장소에는 `examples/retrieval_golden.example.json`
  샘플만 있습니다) — 실제 `project_id`, 실제 chunk_id 기준 정답.
- 정답 판단 시 참고할 원본 PDF(또는 사업계획서 원본) — Chroma 메타데이터의
  페이지 번호와 대조하기 위해 필요합니다.
- baseline 실행에 쓸, 이미 색인이 끝난 Chroma persist 디렉터리.

## Known limitations / 주의사항

- 이 하네스는 검색(retrieval) 품질만 측정합니다. 위원 발언 생성, 위원장
  종합(RAG-005 sufficiency) 품질은 범위 밖입니다(`expected_sufficiency`
  필드는 그 평가를 위해 예약만 해 둔 것입니다).
- `government_support` 도메인은 아직 persona/role 매핑이 확정되지 않아
  (`ai/rag/orchestration/role_mapping.py` 참고) 이 평가셋 스키마에서도 아직
  사용할 수 없습니다.
