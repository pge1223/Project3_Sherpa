import { API_BASE_URL, parseApiResponse } from './client'

function authHeaders() {
  const token = localStorage.getItem('auth_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

// 마이페이지 프로필(전공/학위/졸업, 인턴/공모전/수상, GitHub 통계) — 윤한 GET·PUT /users/me/profile.
export async function getMyProfile() {
  const res = await fetch(`${API_BASE_URL}/users/me/profile`, {
    headers: { ...authHeaders() },
  })
  return parseApiResponse(res, '프로필을 불러오지 못했습니다.')
}

export async function updateMyProfile(profile) {
  const res = await fetch(`${API_BASE_URL}/users/me/profile`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(profile),
  })
  return parseApiResponse(res, '프로필을 저장하지 못했습니다.')
}
