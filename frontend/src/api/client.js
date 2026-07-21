export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

// 가은/Claude(2026-07-21): 실측 제보 — JWT_EXPIRE_MINUTES(60분)가 지난 토큰으로 계속
// API를 호출하면 백엔드가 401 "유효하지 않은 토큰입니다"만 던지는데, 자동 로그인이라
// 화면엔 그 원문 에러만 남고 사용자가 왜 멈췄는지 알 방법이 없었다. 여기서 401을 한 곳에서
// 잡아 토큰을 지우고 로그인 화면으로 보낸다. 로그인 자체의 401(비밀번호 오류)은 별개
// 의미라 authApi.js는 이 헬퍼를 쓰지 않는다.
export function clearExpiredSession() {
  localStorage.removeItem('auth_token')
  if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
    window.location.href = '/login'
  }
}

export async function parseApiResponse(res, fallbackMessage) {
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    if (res.status === 401) clearExpiredSession()
    const detail = Array.isArray(data.detail) ? data.detail.map((d) => d.msg).join(', ') : data.detail
    throw new Error(detail || fallbackMessage)
  }
  return data
}
