import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { login } from '../api/authApi'
import SpaceBackground from '../components/landing/SpaceBackground'
import './LoginPage.css'

export default function LoginPage() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const { access_token } = await login(email, password)
      localStorage.setItem('auth_token', access_token)
      navigate('/projects')
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
          <p style={styles.subtitle}>문서를 놓고 전문가들이 회의하는 AI 위원회</p>

          <form onSubmit={handleSubmit} style={styles.form}>
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
                placeholder="••••••••"
                style={styles.input}
                autoComplete="current-password"
              />
            </label>

            {error && <p style={styles.error}>{error}</p>}

            <button type="submit" disabled={loading} style={styles.button}>
              {loading ? '로그인 중...' : '로그인'}
            </button>
          </form>
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
  },
  card: {
    position: 'relative',
    zIndex: 2,
    width: 360,
    background: '#fff',
    borderRadius: 16,
    border: '1px solid #d9e8f5',
    boxShadow: '0 8px 24px rgba(43, 111, 178, 0.12)',
    padding: '40px 32px',
  },
  logo: {
    display: 'block',
    width: '100%',
    maxWidth: 240,
    height: 'auto',
    margin: '0 auto',
    borderRadius: 10,
  },
  subtitle: {
    margin: '8px 0 32px',
    fontSize: 13,
    color: '#5c7a95',
    textAlign: 'center',
  },
  form: {
    display: 'flex',
    flexDirection: 'column',
    gap: 16,
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
    border: '1px solid #cfe0f0',
    borderRadius: 8,
    outline: 'none',
    background: '#f8fbfe',
    color: '#17324a',
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
    background: '#2f7fd1',
    border: 'none',
    borderRadius: 8,
    cursor: 'pointer',
  },
}
