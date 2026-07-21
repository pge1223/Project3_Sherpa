import { API_BASE_URL } from './client'

function authHeaders() {
  const token = localStorage.getItem('auth_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

// 재인/Claude(2026-07-21): "AI 피드백" 워크벤치 전용 - backend/app/api/routes/workbench.py
// (완전히 새 파일, 경이님 파이프라인/스키마와 무관)를 호출해서, 위원이 애초에 인용한
// evidence.chunk_id로 벡터DB에서 청크 원문을 ID 직접 조회한다(AI 호출 없음, 항상 원문
// 그대로). lookups에 없는 id는 매칭을 시도하지 않으므로, 호출 전에 chunkId가 있는
// 항목만 걸러서 넘겨야 한다.
export async function getQuoteMatches(projectId, lookups) {
  const res = await fetch(`${API_BASE_URL}/workbench/${projectId}/quotes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({
      lookups: lookups.map((l) => ({ id: l.id, chunk_id: l.chunkId })),
    }),
  })
  const data = await res.json()
  if (!res.ok) {
    throw new Error(data.detail || '인용 조회에 실패했습니다.')
  }
  return data.matches // [{id, quote, found}]
}
