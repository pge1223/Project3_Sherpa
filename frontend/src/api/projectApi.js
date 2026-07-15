import { API_BASE_URL } from './client'

function authHeaders() {
  const token = localStorage.getItem('auth_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function getProjects() {
  const res = await fetch(`${API_BASE_URL}/projects/`, {
    headers: { ...authHeaders() },
  })
  const data = await res.json()
  if (!res.ok) {
    throw new Error(data.detail || '프로젝트 목록을 불러오지 못했습니다.')
  }
  return data
}

export async function createProject({ title, doc_type, description }) {
  const res = await fetch(`${API_BASE_URL}/projects/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ title, doc_type, description }),
  })
  const data = await res.json()
  if (!res.ok) {
    throw new Error(data.detail || '프로젝트를 생성하지 못했습니다.')
  }
  return data
}

export async function analyzeProject(projectId) {
  const res = await fetch(`${API_BASE_URL}/projects/${projectId}/analyze`, {
    method: 'POST',
    headers: { ...authHeaders() },
  })
  const data = await res.json()
  if (!res.ok) {
    throw new Error(data.detail || '분석을 시작하지 못했습니다.')
  }
  return data
}
