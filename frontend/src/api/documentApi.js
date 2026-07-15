import { API_BASE_URL } from './client'

function authHeaders() {
  const token = localStorage.getItem('auth_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function uploadDocument(projectId, file, sourceType = 'pdf') {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('source_type', sourceType)

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

export async function fetchUrl(url) {
  const res = await fetch(`${API_BASE_URL}/documents/fetch-url`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ url }),
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
