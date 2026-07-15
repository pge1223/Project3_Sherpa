import os
import uuid
from fastapi import APIRouter, HTTPException, Header, UploadFile, File, Form
from app.schemas.document import DocumentResponse
from app.repositories.document_repository import DocumentRepository
from app.models.document import DocumentModel
from app.config import settings
from jose import jwt, JWTError

router = APIRouter(prefix="/documents", tags=["documents"])
document_repo = DocumentRepository()

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

def get_current_user(authorization: str) -> str:
    try:
        token = authorization.replace("Bearer ", "")
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다")

# DOC-001: 문서 업로드
@router.post("/{project_id}", response_model=DocumentResponse)
async def upload_document(
    project_id: str,
    file: UploadFile = File(...),
    source_type: str = Form("pdf"),
    authorization: str = Header(..., alias="authorization"),
):
    user_email = get_current_user(authorization)

    stored_filename = f"{uuid.uuid4()}_{file.filename}"
    file_path = os.path.join(UPLOAD_DIR, stored_filename)

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    # DOC-002: 문서 메타데이터 저장
    document = DocumentModel(
        project_id=project_id,
        user_email=user_email,
        original_filename=file.filename,
        stored_filename=stored_filename,
        file_path=file_path,
        file_size=len(content),
        mime_type=file.content_type or "application/octet-stream",
        source_type=source_type,
    )

    result = await document_repo.create(document)

    return DocumentResponse(
        id=result,
        project_id=document.project_id,
        user_email=document.user_email,
        original_filename=document.original_filename,
        stored_filename=document.stored_filename,
        file_path=document.file_path,
        file_size=document.file_size,
        mime_type=document.mime_type,
        source_type=document.source_type,
        status=document.status,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )

# DOC-003: 프로젝트 문서 목록 조회
@router.get("/{project_id}", response_model=list[DocumentResponse])
async def get_documents(
    project_id: str,
    authorization: str = Header(..., alias="authorization"),
):
    user_email = get_current_user(authorization)
    documents = await document_repo.find_by_project_id(project_id)

    return [
        DocumentResponse(
            id=str(d["_id"]),
            project_id=d["project_id"],
            user_email=d["user_email"],
            original_filename=d["original_filename"],
            stored_filename=d["stored_filename"],
            file_path=d["file_path"],
            file_size=d["file_size"],
            mime_type=d["mime_type"],
            source_type=d["source_type"],
            status=d["status"],
            created_at=d["created_at"],
            updated_at=d["updated_at"],
        )
        for d in documents
    ]