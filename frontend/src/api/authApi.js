import { API_BASE_URL } from './client'

export async function login(email, password) {
  if (!email || !password) {
    throw new Error('이메일과 비밀번호를 입력해주세요.')
  }

  const res = await fetch(`${API_BASE_URL}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })

  const data = await res.json()
  if (!res.ok) {
    throw new Error(data.detail || '이메일 또는 비밀번호가 올바르지 않습니다.')
  }
  return data
}
