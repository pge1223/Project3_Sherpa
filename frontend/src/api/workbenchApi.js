import { API_BASE_URL, parseApiResponse } from './client'

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
  const data = await parseApiResponse(res, '인용 조회에 실패했습니다.')
  return data.matches // [{id, quote, found}]
}

// 재인/Claude(2026-07-21): "맥락 이상 감지" - 문서 자체 임베딩 통계 + LLM 재판단으로
// 걸러진 결과를 가져온다(사용자 확인: 오탈자 검출은 보류, 이것만 먼저 구현). AI 호출
// 없이 캐시된 값이 있으면 그대로 재사용되므로, 워크벤치 진입마다 불러도 무방하다.
export async function getContextCheck(projectId) {
  const res = await fetch(`${API_BASE_URL}/workbench/${projectId}/context-check`, {
    headers: { ...authHeaders() },
  })
  const data = await parseApiResponse(res, '맥락 이상 감지에 실패했습니다.')
  return data.findings // [{id, quote, message}]
}
