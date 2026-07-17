# RAG-006 — 유사 성공 사례 검색

## 1. 목적

현재 평가 중인 문서와 유사한 **공개 수상작·선정 사례·가이드 자료**를 검색해,
출처와 함께 공통점·차이점·현재 문서에서 보완이 필요한 부분을 제시한다.

## 2. RAG-003과의 차이

| | RAG-003 (역할 기반 검색) | RAG-006 (유사 사례 검색) |
|---|---|---|
| 검색 대상 | 현재 프로젝트에 업로드된 문서 | 별도 구축된 공개 사례 데이터셋 |
| Chroma 컬렉션 | `project_documents_kure_v1` (project_id로 논리적 격리) | `similar_success_cases` (완전히 별도 컬렉션) |
| 용도 | 평가 점수·판단의 **직접 근거** | 비교·개선 방향을 위한 **참고 자료** |
| 필터 | project_id, document_id, role_id | domain, case_id |

두 모듈은 서로 다른 Chroma 컬렉션을 쓰므로 데이터가 섞이지 않는다. RAG-006은
`ai.rag.role_retrieval`, `ai.rag.evidence_linking`, `ai.rag.evidence_sufficiency`,
`ai.rag.integration.meeting_evidence_adapter`의 기존 코드를 전혀 수정하지 않는다.

## 3. 사례 데이터 형식

`SimilarCaseDocument` (`schemas.py`) — 사례 청크 1건:

```python
from ai.rag.similar_cases import SimilarCaseDocument, SimilarCaseType

case = SimilarCaseDocument(
    case_id="CASE-001",
    title="공공데이터 활용 공모전 수상작",
    case_type=SimilarCaseType.AWARD_WINNER,
    domain="public_service",
    evaluation_criteria=["문제 정의", "기술성", "사업성"],
    source_name="공모전 공식 홈페이지",
    source_url="https://example.org/award/2024/001",
    document_id="DOC-CASE-001",
    chunk_id="CHUNK-CASE-001-001",
    content="본 서비스는 공공데이터를 활용해 ...",
    page=3,
    section="서비스 구성",
)
```

`case_id, title, case_type, source_name, source_url, document_id, chunk_id, content`는
필수이며 빈 문자열이면 `SimilarCaseValidationError`가 발생한다. **`SimilarCaseType.REJECTED_CASE`는
실제 탈락 사례 데이터가 있을 때만 사용한다** — 데이터가 없다고 임의로 만들어내지 않는다.

## 4. 사례 데이터 색인 방법

기존 `KUREEmbedder`와 Chroma 인프라를 그대로 재사용한다(`embed_query()`로 청크
1건씩 임베딩 — `ChunkingResult` 기반 배치 임베딩은 문서 파싱 전용이라 사례 색인에는
맞지 않아 쓰지 않았다). 새 임베딩 모델을 추가하지 않았다.

```python
import chromadb
from ai.rag.embedding.kure_embedder import KUREEmbedder
from ai.rag.similar_cases import SimilarCaseIndexingService, SimilarCaseRepository, SimilarCaseConfig

config = SimilarCaseConfig()  # RAG_SIMILAR_CASES_* 환경변수로 오버라이드 가능
client = chromadb.PersistentClient(path="./chroma_data")
embedder = KUREEmbedder()

repository = SimilarCaseRepository(
    client=client,
    collection_name=config.collection_name,
    embedding_model=embedder.model_name,
    embedding_dimension=embedder.embedding_dimension,
    embedding_version="embedding_v1",
)
indexing_service = SimilarCaseIndexingService(repository, embedder)

summary = indexing_service.index_cases([case], trace_id="batch-001")
print(summary.indexed_count, summary.skipped_count, summary.warnings)
```

동일한 `(document_id, chunk_id)`는 upsert로 덮어써지므로 재색인해도 중복되지 않는다.
content가 비어 있는 항목은 개별적으로 건너뛰고(`warnings`에 기록), 배치 전체를
실패시키지 않는다.

## 5. 서비스 호출 예시 (LangGraph 없이 단독 실행)

```python
from ai.rag.similar_cases import (
    SimilarCaseConfig,
    SimilarCaseRepository,
    SimilarCaseSearchRequest,
    SimilarCaseSearchService,
)

repository = SimilarCaseRepository(
    client=client,
    collection_name=config.collection_name,
    embedding_model=embedder.model_name,
    embedding_dimension=embedder.embedding_dimension,
    embedding_version="embedding_v1",
)
search_service = SimilarCaseSearchService(repository, embedder, config=config)

response = search_service.search(
    SimilarCaseSearchRequest(
        document_summary="AI를 활용해 공공기관의 사업계획서를 자동 평가하는 서비스",
        domain="공공서비스 AI",
        evaluation_criteria=["문제 정의", "기술 구현 가능성", "사회적 가치"],
        top_k=5,
        trace_id="meeting-42",
    )
)
```

`ai.meeting.graph`, LangGraph runtime, reviewer/chair 노드를 import하지 않으며,
`pytest ai/rag/tests/test_similar_case_*.py` 만으로 완전히 독립적으로 테스트할 수 있다.

## 6. 반환값 예시

```json
{
  "results": [
    {
      "case_id": "CASE-001",
      "title": "공공데이터 활용 공모전 수상작",
      "case_type": "award_winner",
      "domain": "public_service",
      "source_name": "공모전 공식 홈페이지",
      "source_url": "https://example.org/award/2024/001",
      "similarity_score": 0.82,
      "matched_criteria": ["기술성"],
      "similarity_reasons": [
        "두 문서 모두 'public_service' 도메인에 속합니다.",
        "동일한 평가 항목(기술성)을 다룹니다."
      ],
      "common_points": ["평가 항목 '기술성'이(가) 현재 문서와 사례 모두에서 확인됩니다."],
      "different_points": ["사례에는 평가 항목 '사업성'에 해당하는 내용이 포함되어 있습니다."],
      "current_document_gaps": [
        "제공된 현재 문서 요약과 근거에서는 '사업성' 관련 내용을 확인하기 어렵습니다."
      ],
      "evidence": [
        {
          "document_id": "DOC-CASE-001",
          "chunk_id": "CHUNK-CASE-001-001",
          "page": 3,
          "section": "서비스 구성",
          "quote": "본 서비스는 공공데이터를 활용해 ...",
          "similarity_score": 0.82
        }
      ],
      "reference_only": true
    }
  ],
  "total_results": 1,
  "has_rejected_cases": false,
  "comparison_mode": "selected_case_gap",
  "query_text": "도메인: 공공서비스 AI\n평가 항목: 문제 정의, 기술 구현 가능성, 사회적 가치\n문서 요약: ...",
  "trace_id": "meeting-42",
  "warnings": ["탈락 사례 데이터가 없어 선정 사례와 비교한 부족 항목으로 표시했습니다."],
  "reference_only": true
}
```

## 7. 사례 출처 표시 방식

모든 `SimilarCaseResult`는 `source_name`, `source_url`, `evidence[].document_id`,
`evidence[].chunk_id`, `evidence[].page`/`section`, `evidence[].quote`를 포함한다.
`source_url`은 항상 색인 시점에 저장된 `SimilarCaseDocument.source_url` 값 그대로이며,
**LLM이 생성하지 않는다.** 색인된 청크 중 `source_name`/`source_url`이 없는 사례는
검색 결과 집계 단계에서 제외되고, 몇 건이 제외됐는지 `warnings`에 기록된다.

## 8. 유사 이유 생성 방식

기본은 **규칙 기반(결정론적)** 생성이다 (`comparison_service._compare_rule_based`):
현재 문서 요약/평가 항목과 검색된 사례 청크·metadata만 사용해 (1) 도메인 일치,
(2) 평가 항목 교집합, (3) 문서 요약과 사례 청크의 키워드 겹침(`ai.rag.evidence_linking.
relevance.extract_keywords` 재사용)만으로 이유를 만든다. 검색되지 않은 사례 내용이나
모델의 일반 지식을 사실처럼 쓰지 않으며, 겹치는 근거가 전혀 없으면 빈 배열을 반환한다
(점수가 높다는 이유만 반복하지 않는다).

**LLM은 완전히 선택 사항**이다. `SimilarCaseSearchService(..., llm_call=my_llm_call)`처럼
`str -> str` 콜러블을 주입하면 사용되고, 없으면 규칙 기반만 쓴다. 이 모듈은 새
LLM 공급자/클라이언트를 만들지 않는다 — 호출자가 기존 프로젝트의 LLM 호출 방식으로
구현한 콜러블을 그대로 넘기면 된다. LLM 응답은 엄격한 JSON 파싱을 거치고, 파싱
실패·필수 키 누락·타입 불일치 시 예외 없이 규칙 기반 결과로 자동 전환된다
(`compare_case()`는 항상 결과를 반환하며 예외를 던지지 않는다). `evidence`(quote)는
LLM이 아니라 항상 실제 검색된 청크 원문에서 `search_service`가 직접 만들기 때문에,
존재하지 않는 근거를 참조하는 문제가 구조적으로 발생하지 않는다.

## 9. 탈락 사례가 없을 때 처리 방식

색인된 사례에 `SimilarCaseType.REJECTED_CASE`가 하나도 없으면:

- `has_rejected_cases = false`
- `comparison_mode = "selected_case_gap"`
- `warnings`에 `"탈락 사례 데이터가 없어 선정 사례와 비교한 부족 항목으로 표시했습니다."` 추가
- `different_points`/`current_document_gaps`는 선정 사례(AWARD_WINNER/SELECTED_CASE/GUIDE)와의
  평가 항목·키워드 차이만으로 구성되며, 탈락 원인을 추정하지 않는다.

실제 `REJECTED_CASE` 데이터가 검색 결과에 포함된 경우에만
`comparison_mode = "selected_and_rejected_cases"`가 되고, `has_rejected_cases = true`가
된다. 탈락 사례에 대해서는 평가 항목/키워드 불일치를 근거로 "부족점"을 만들지 않는다
(탈락 원인을 일반 지식으로 지어내지 않기 위함).

## 10. LangGraph 없이 단독 실행하는 방법

이 패키지의 어떤 파일도 `ai.meeting.graph`, LangGraph, reviewer/chair 노드를
import하지 않는다. 5번의 호출 예시처럼 `SimilarCaseRepository` + 임베더만 있으면
바로 실행/테스트할 수 있다.

## 11. 회의 파이프라인에 전달할 JSON 예시

회의 파이프라인 담당자는 `SimilarCaseSearchResponse.model_dump()`를 그대로
프롬프트/상태에 넣으면 된다 (6번 예시가 그 결과와 동일하다). 이 모듈은
`ai/meeting/graph`를 수정하지 않으며, 통합은 호출하는 쪽의 책임이다:

```python
response = search_service.search(request)
similar_cases_payload = response.model_dump()
```

## 12. 주의사항 — 유사 사례는 점수 근거가 아니다

`SimilarCaseResult.reference_only`와 `SimilarCaseSearchResponse.reference_only`는
항상 `true`다. 유사 사례가 높은 점수를 받았다는 이유만으로 현재 문서의 평가 점수를
올리면 안 되며, RAG-006 결과가 RAG-005(`EvidenceSufficiencyService`)의 근거 충족도
판정이나 숫자 점수 허용 정책을 자동으로 바꾸지 않는다 — 이 모듈은 RAG-005 코드를
전혀 참조하지 않는다. 유사 사례는 오직 비교·개선 방향 제시용 참고 자료다.

## 13. 현재 한계와 미검증 항목

- 실제 공개 수상작/선정 사례 데이터셋이 없어 **진짜 사례 데이터로 색인·검색을
  수행한 적이 없다.** 모든 테스트는 fixture로 만든 가짜 사례 데이터와, KURE-v1 대신
  `conftest.py`의 `fake_kure_embedder`(고정 차원 벡터를 반환하는 fake)를 사용했다.
- LLM 경로(`llm_call` 주입)는 mock 콜러블로만 테스트했고, 실제 OpenAI/다른 LLM
  응답 품질(사실 왜곡, 존재하지 않는 수치 생성 여부 등)은 검증하지 못했다 — 실제
  연동 시 반드시 별도 검증이 필요하다.
- 규칙 기반 유사 이유/공통점/차이점 생성은 키워드 겹침 기반의 단순 휴리스틱이라,
  의미적으로는 유사하지만 표면 키워드가 겹치지 않는 사례는 이유를 하나도 찾지
  못해 `similarity_reasons=[]`가 될 수 있다(의도된 동작이지만 활용성엔 한계가 있음).
- domain 필터는 정확 일치(exact match) 문자열 비교만 지원한다 — 유의어/상위
  카테고리 매칭은 하지 않는다.
