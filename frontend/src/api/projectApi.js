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

export async function getProject(projectId) {
  const res = await fetch(`${API_BASE_URL}/projects/${projectId}`, {
    headers: { ...authHeaders() },
  })
  const data = await res.json()
  if (!res.ok) {
    throw new Error(data.detail || '프로젝트를 불러오지 못했습니다.')
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

// committee: 선택한 멘토 persona_id 2~4개(MentorSelectionPage). 생략하면 백엔드가
// rubric_mapping의 전체 committee를 그대로 쓴다(기존 호출 호환).
// progressToken: 진짜 진행률 폴링용(getAnalyzeProgress) — 호출부가 POST 전에 미리
// crypto.randomUUID() 등으로 만들어 넘긴다. analyze()는 완료될 때까지 응답이 없는 동기
// 호출이라, 그 사이 상태를 보려면 별도 토큰이 필요하다(meeting_id는 완료 후에만 앎).
export async function analyzeProject(projectId, committee, progressToken) {
  const body = committee || progressToken ? { committee, progress_token: progressToken } : undefined
  const res = await fetch(`${API_BASE_URL}/projects/${projectId}/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await res.json()
  if (!res.ok) {
    throw new Error(data.detail || '분석을 시작하지 못했습니다.')
  }
  return data
}

// FeedbackProgressPage가 analyzeProject() 진행 중 주기적으로 불러 실제 진행 상황(위원별
// 검토/채점/위원장 종합 단계)을 읽는다. 토큰을 아직 서버가 모르거나(POST가 아직 도착 전)
// 이미 끝나서 지워졌으면 백엔드가 빈 기본값을 준다 — 최종 완료 판단은 이 값이 아니라
// analyzeProject()의 resolve/reject로 한다.
export async function getAnalyzeProgress(projectId, progressToken) {
  const res = await fetch(
    `${API_BASE_URL}/projects/${projectId}/analyze/progress?token=${encodeURIComponent(progressToken)}`,
    { headers: { ...authHeaders() } },
  )
  if (!res.ok) return null
  return res.json()
}

// STEP7 "대화형 피드백" 화면 — 저장된 회의 결과를 근거로 위원장이 후속 질문에 답한다.
// history: 이번 세션에서 오간 이전 질문/답변([{question, answer}, ...]) — 서버가 대화를
// 저장하지 않는 stateless 호출이라 문맥 유지하려면 매번 그대로 다시 넘겨야 한다.
export async function askCommittee(projectId, question, history) {
  const res = await fetch(`${API_BASE_URL}/projects/${projectId}/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ question, history }),
  })
  const data = await res.json()
  if (!res.ok) {
    throw new Error(data.detail || '답변을 받아오지 못했습니다.')
  }
  return data
}

// 가은/Claude(2026-07-17): "결과 정리"(ProjectDetailPage)가 위원장 종합(백그라운드로
// 늦게 끝남)을 기다리는 동안 폴링용으로 쓴다 — RPT-001 기존 엔드포인트 재사용, 새
// 엔드포인트 아님. 최신 Mongo 회의 기록을 그대로 반환하므로 백그라운드 작업이
// chair_summary를 patch하면 다음 폴링에서 바로 보인다.
export async function getProjectReport(projectId) {
  const res = await fetch(`${API_BASE_URL}/projects/${projectId}/report`, {
    headers: { ...authHeaders() },
  })
  const data = await res.json()
  if (!res.ok) {
    throw new Error(data.detail || '결과를 불러오지 못했습니다.')
  }
  return data
}

// STEP4 "공모전 분석" 화면 — 문서 성격 태그 + 추천 멘토 후보(도메인 고정 4명 + LLM이 붙인
// fit_tag)를 가져온다. 실제 OpenAI 호출 1회(짧은 프롬프트라 수 초 내).
export async function getMentorCandidates(projectId) {
  const res = await fetch(`${API_BASE_URL}/projects/${projectId}/mentor-candidates`, {
    method: 'POST',
    headers: { ...authHeaders() },
  })
  const data = await res.json()
  if (!res.ok) {
    throw new Error(data.detail || '추천 멘토를 불러오지 못했습니다.')
  }
  return data
}
