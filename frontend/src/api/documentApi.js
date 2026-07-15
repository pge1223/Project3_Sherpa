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

// projectId가 있어야 공고문이 RAG 색인까지 되고 documents 컬렉션에 저장된다(document_role: 'criteria').
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
