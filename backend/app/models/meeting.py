# 작성자: 가은/Claude (2026-07-15, MTG-005 — 윤한 합의)
# 목적: 회의 결과(review_output.schema.json v2)를 MongoDB에 저장하는 모델.
#       v2 문서 필드(schema_version~media_script) 그대로에 더해, v2 스키마엔 없지만
#       MTG-007(특정 위원 재평가)이 재구성 없이 그대로 이어받을 수 있도록
#       committee/submission/retrieved_evidence를 함께 저장한다.
# 가은/Claude(2026-07-16): document_id 필드 추가 — 경이의 rerun_reviewer()
# (ai/meeting/graph/rerun.py)가 previous_document["document_id"]를 그대로 요구해서
# (assemble_document()가 v2 문서에 document_id를 다시 채워 넣음) 필요해졌다. 이 필드
# 추가 전에 저장된 기존 meetings 레코드에는 document_id가 없으니, 그 레코드로
# 재평가를 시도하면 KeyError가 날 수 있다 — 새로 분석을 돌린 회의부터 정상 동작.
from datetime import datetime
from typing import Optional
from bson import ObjectId


class MeetingModel:
    collection_name = "meetings"

    def __init__(
        self,
        project_id: str,
        user_email: str,
        meeting_id: str,
        domain: str,
        title: str,
        status: str,
        document_id: str,
        rubric: dict,
        committee: list,
        submission: dict,
        retrieved_evidence: list,
        reviewer_results: list,
        score_result: Optional[dict] = None,
        chair_summary: Optional[dict] = None,
        top_revisions: Optional[list] = None,
        evidence: Optional[list] = None,
        media_script: Optional[list] = None,
        schema_version: str = "2.0.0",
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        _id: Optional[ObjectId] = None,
    ):
        self._id = _id
        self.project_id = project_id
        self.user_email = user_email
        self.meeting_id = meeting_id
        self.domain = domain
        self.title = title
        self.status = status
        self.document_id = document_id
        self.rubric = rubric
        self.committee = committee
        self.submission = submission
        self.retrieved_evidence = retrieved_evidence
        self.reviewer_results = reviewer_results
        self.score_result = score_result
        self.chair_summary = chair_summary
        self.top_revisions = top_revisions or []
        self.evidence = evidence or []
        self.media_script = media_script or []
        self.schema_version = schema_version
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "user_email": self.user_email,
            "meeting_id": self.meeting_id,
            "domain": self.domain,
            "title": self.title,
            "status": self.status,
            "document_id": self.document_id,
            "rubric": self.rubric,
            "committee": self.committee,
            "submission": self.submission,
            "retrieved_evidence": self.retrieved_evidence,
            "reviewer_results": self.reviewer_results,
            "score_result": self.score_result,
            "chair_summary": self.chair_summary,
            "top_revisions": self.top_revisions,
            "evidence": self.evidence,
            "media_script": self.media_script,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
