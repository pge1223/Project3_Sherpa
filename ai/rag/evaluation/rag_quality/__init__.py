# 작성자: 용준/Claude(2026-07-22)
# 목적: RAG 품질 오프라인 평가 도구(Recall@5/Faithfulness/Hallucination Rate/Persona
#       Evidence Fit). 기존 ai/rag/evaluation/(레거시 배치 위원회 domain/persona_id 체계,
#       EvaluationCase가 ai.rag.orchestration.role_mapping.resolve_role_id로 엄격 검증)와는
#       별도 병렬 패키지다 — ideation 대화(planning_expert/dev_expert)는 그 검증 체계에 속하지
#       않는 별도 ID 공간이라 억지로 끼워 넣지 않았다(계획 문서 참고). metrics.py의 순수 함수는
#       도메인에 종속되지 않으므로 이 패키지가 그대로 import해 재사용한다.
