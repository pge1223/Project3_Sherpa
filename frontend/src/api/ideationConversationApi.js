import { API_BASE_URL } from './client'

// 용준/Claude(2026-07-20): 개발용 "대화형 아이디어 발전 회의" 프리뷰 API 호출부.
// backend/app/api/routes/ideation_conversation_preview.py(ENABLE_IDEATION_PREVIEW=true일
// 때만 존재하는 라우터)를 그대로 호출한다. 기존 ideationApi.js(배치형)와 같은 컨벤션
// (axios 없이 fetch, authHeaders() 로컬 재정의)을 따른다.
function authHeaders() {
  const token = localStorage.getItem('auth_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function handleResponse(res) {
  const data = await res.json()
  if (!res.ok) {
    throw new Error(data.detail || '아이디어 회의 프리뷰 요청에 실패했습니다.')
  }
  return data
}

export async function startIdeationConversation({
  competitionName,
  competitionDocument,
  userIdea,
  maxRounds = 3,
  useRag = false,
  projectId,
  model,
}) {
  const res = await fetch(`${API_BASE_URL}/ideation-conversation/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({
      competition_name: competitionName,
      competition_document: competitionDocument,
      user_idea: userIdea,
      max_rounds: maxRounds,
      use_rag: useRag,
      project_id: useRag ? projectId : undefined,
      model: model || undefined,
    }),
  })
  return handleResponse(res)
}

export async function replyIdeationConversation(sessionId, message, model) {
  const res = await fetch(`${API_BASE_URL}/ideation-conversation/${sessionId}/reply`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ message, model: model || undefined }),
  })
  return handleResponse(res)
}

export async function finalizeIdeationConversation(sessionId, model) {
  const res = await fetch(`${API_BASE_URL}/ideation-conversation/${sessionId}/finalize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ model: model || undefined }),
  })
  return handleResponse(res)
}

export async function getIdeationConversation(sessionId) {
  const res = await fetch(`${API_BASE_URL}/ideation-conversation/${sessionId}`, {
    headers: { ...authHeaders() },
  })
  return handleResponse(res)
}
