import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { register } from '../api/authApi'
import SpaceBackground from '../components/landing/SpaceBackground'
import './LoginPage.css'

export default function RegisterPage() {
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [passwordConfirm, setPasswordConfirm] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')

    if (password !== passwordConfirm) {
      setError('비밀번호가 일치하지 않습니다.')
      return
    }

    setLoading(true)
    try {
      await register({ name, email, password })
      navigate('/login')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={styles.page}>
      <SpaceBackground />
      <div className="login-card-glow">
        <div style={styles.card}>
          <img src="/images/logo1.png" alt="AI Review Board" style={styles.logo} />
          <p style={styles.subtitle}>계정을 만들고 AI 심사위원 회의실로 입장하세요.</p>

          <form onSubmit={handleSubmit} style={styles.form}>
            <label style={styles.label}>
              이름
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="홍길동"
                style={styles.input}
                autoComplete="name"
              />
            </label>

            <label style={styles.label}>
              이메일
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                style={styles.input}
                autoComplete="email"
              />
            </label>

            <label style={styles.label}>
              비밀번호
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="8자 이상 권장"
                style={styles.input}
                autoComplete="new-password"
              />
            </label>

            <label style={styles.label}>
              비밀번호 확인
              <input
                type="password"
                value={passwordConfirm}
                onChange={(e) => setPasswordConfirm(e.target.value)}
                placeholder="비밀번호를 다시 입력"
                style={styles.input}
                autoComplete="new-password"
              />
            </label>

            {error && <p style={styles.error}>{error}</p>}

            <button type="submit" disabled={loading} style={styles.button}>
              {loading ? '가입 중...' : '회원가입'}
            </button>
          </form>

          <button type="button" style={styles.secondaryButton} onClick={() => navigate('/login')}>
            로그인으로 돌아가기
          </button>
        </div>
      </div>
    </div>
  )
}

const styles = {
  page: {
    position: 'relative',
    zIndex: 1,
    minHeight: '100vh',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '24px 16px',
  },
  card: {
    position: 'relative',
    zIndex: 2,
    width: 380,
    maxWidth: '100%',
    background: '#fff',
    borderRadius: 16,
    border: '1px solid #ece9f7',
    boxShadow: '0 8px 24px rgba(124, 77, 255, 0.12)',
    padding: '36px 32px',
  },
  logo: {
    display: 'block',
    width: '100%',
    maxWidth: 220,
    height: 'auto',
    margin: '0 auto',
    borderRadius: 10,
  },
  subtitle: {
    margin: '8px 0 28px',
    fontSize: 13,
    color: '#5c7a95',
    textAlign: 'center',
  },
  form: {
    display: 'flex',
    flexDirection: 'column',
    gap: 14,
  },
  label: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
    fontSize: 13,
    color: '#3d5a75',
  },
  input: {
    padding: '10px 12px',
    fontSize: 14,
    border: '1px solid #ded9f2',
    borderRadius: 8,
    outline: 'none',
    background: '#faf9ff',
    color: '#1f2333',
  },
  error: {
    margin: 0,
    fontSize: 13,
    color: '#d64545',
  },
  button: {
    marginTop: 8,
    padding: '12px',
    fontSize: 14,
    fontWeight: 600,
    color: '#fff',
    background: '#7c4dff',
    border: 'none',
    borderRadius: 8,
    cursor: 'pointer',
  },
  secondaryButton: {
    marginTop: 10,
    width: '100%',
    padding: '12px',
    fontSize: 14,
    fontWeight: 600,
    color: '#4b4f63',
    background: 'transparent',
    border: '1px solid #ded9f2',
    borderRadius: 8,
    cursor: 'pointer',
  },
}
