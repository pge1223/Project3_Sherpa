import { API_BASE_URL } from './client'

function authHeaders() {
  const token = localStorage.getItem('auth_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

// document_role: 'target'(평가 대상 문서/기획서, 기본값) | 'criteria'(공고문·평가기준)
export async function uploadDocument(projectId, file, sourceType = 'pdf', documentRole = 'target') {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('source_type', sourceType)
  formData.append('document_role', documentRole)

  const res = await fetch(`${API_BASE_URL}/documents/${projectId}`, {
    method: 'POST',
    headers: { ...authHeaders() },
    body: formData,
  })
  const data = await res.json()
  if (!res.ok) {
    throw new Error(data.detail || '문서를 업로드하지 못했습니다.')
  }
  return data
}

// 가은/Claude(2026-07-21): 실측 요청 — /board에서 URL/파일로 잘못 올린 공고문·평가기준
// 문서를 지울 수 있게. Chroma 벡터 청크까지 같이 정리되는 DELETE /documents/{project_id}
// /{document_id}(신규)를 호출한다.
export async function deleteDocument(projectId, documentId) {
  const res = await fetch(`${API_BASE_URL}/documents/${projectId}/${documentId}`, {
    method: 'DELETE',
    headers: { ...authHeaders() },
  })
  const data = await res.json()
  if (!res.ok) {
    throw new Error(data.detail || '문서를 삭제하지 못했습니다.')
  }
  return data
}

// 가은/Claude(2026-07-16): StepSidebar에서 진행 중이던 프로젝트로 "이어서" 업로드 화면에
// 돌아올 수 있게 하면서 필요해짐 — 이미 업로드된 문서 목록을 다시 불러와 화면에 채운다.
export async function getDocuments(projectId) {
  const res = await fetch(`${API_BASE_URL}/documents/${projectId}`, {
    headers: { ...authHeaders() },
  })
  const data = await res.json()
  if (!res.ok) {
    throw new Error(data.detail || '문서 목록을 불러오지 못했습니다.')
  }
  return data
}

// projectId가 있어야 공고문이 RAG 색인까지 되고 documents 컬렉션에 저장된다(document_role: 'criteria').
// 가은/Claude(2026-07-19, INF-007): 색인(청킹+임베딩)이 더 이상 이 응답을 막지 않는다 —
// project_id를 줬으면 응답에 document_id/document_status("indexing")가 같이 온다.
// 색인 완료 여부는 getDocumentStatus()로 폴링해서 확인해야 한다.
export async function fetchUrl(url, projectId) {
  const res = await fetch(`${API_BASE_URL}/documents/fetch-url`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ url, project_id: projectId }),
  })
  const data = await res.json()
  if (!res.ok) {
    const message = Array.isArray(data.detail)
      ? data.detail.map((d) => d.msg).join(', ')
      : data.detail
    throw new Error(message || 'URL 문서를 가져오지 못했습니다.')
  }
  return data
}

// 가은/Claude(2026-07-19, INF-007): fetch-url이 색인을 백그라운드로 넘기면서 필요해짐 —
// document.status가 "indexing"인 동안 짧은 간격으로 이 엔드포인트(기존 DOC-004)를
// 폴링해서 "indexed"/"indexed_empty"/"indexing_failed"/"indexing_timeout"으로 바뀌는지
// 확인한다. getDocuments()(문서 목록 전체 조회)보다 가벼워서 폴링용으로 이걸 쓴다.
export async function getDocumentStatus(projectId, documentId) {
  const res = await fetch(`${API_BASE_URL}/documents/${projectId}/${documentId}/status`, {
    headers: { ...authHeaders() },
  })
  const data = await res.json()
  if (!res.ok) {
    throw new Error(data.detail || '문서 상태를 확인하지 못했습니다.')
  }
  return data
}

// 가은/Claude(2026-07-21): "공모전 분석" 화면(ReviewBoardPrototype.jsx) — 이미 수집된
// criteria 문서(공고문)를 근거로 official_facts(공고문에 실제 있는 사실)/
// strategic_analysis(AI 추론)/evidence를 분리해서 받는다. 공고문을 하나도 안 넣었으면
// has_announcement: false만 오고 LLM은 호출되지 않는다(백엔드에서 지어내지 않음).
export async function getAnnouncementAnalysis(projectId) {
  const res = await fetch(`${API_BASE_URL}/documents/${projectId}/announcement-analysis`, {
    method: 'POST',
    headers: { ...authHeaders() },
  })
  const data = await res.json()
  if (!res.ok) {
    throw new Error(data.detail || '공고문 분석을 불러오지 못했습니다.')
  }
  return data
}

// 재인/Claude(2026-07-21): "AI 피드백"(워크벤치) 화면 — 기획서 원문(parsed_text)을
// 가져와 중앙에 띄우는 용도. 백엔드에 이미 있던 GET /{project_id}/{document_id}/preview
// (DOC-006, 원본 소유자는 이 문서 미리보기 기능을 만든 담당자)를 그대로 호출만 한다 -
// 새 백엔드 엔드포인트를 추가한 게 아니라 기존 걸 프론트에서 처음 불러쓰는 것.
export async function getDocumentPreview(projectId, documentId) {
  const res = await fetch(`${API_BASE_URL}/documents/${projectId}/${documentId}/preview`, {
    headers: { ...authHeaders() },
  })
  const data = await res.json()
  if (!res.ok) {
    throw new Error(data.detail || '문서 원문을 불러오지 못했습니다.')
  }
  return data
}
