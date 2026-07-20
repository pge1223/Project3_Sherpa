import { API_BASE_URL } from './client'

// 용준/Claude(2026-07-20): 개발용 "아이디어 발전 회의" 프리뷰 API 호출부. 정식 기능이
// 아니라 backend/app/api/routes/ideation_preview.py(ENABLE_IDEATION_PREVIEW=true일 때만
// 존재하는 라우터)를 그대로 호출한다. 다른 api/*.js 파일과 같은 컨벤션(axios 없이 fetch,
// authHeaders() 로컬 재정의)을 따른다 — 단, 이 엔드포인트는 인증을 요구하지 않지만
// 다른 파일들과 형태를 맞춰 그대로 둔다.
function authHeaders() {
  const token = localStorage.getItem('auth_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function previewIdeationMeeting({
  competitionName,
  competitionDocument,
  userIdea,
  maxRounds = 1,
  useRag = false,
  projectId,
}) {
  const res = await fetch(`${API_BASE_URL}/ideation-preview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({
      competition_name: competitionName,
      competition_document: competitionDocument,
      user_idea: userIdea,
      max_rounds: maxRounds,
      use_rag: useRag,
      project_id: useRag ? projectId : undefined,
    }),
  })
  const data = await res.json()
  if (!res.ok) {
    throw new Error(data.detail || '아이디어 회의 프리뷰 실행에 실패했습니다.')
  }
  return data
}
