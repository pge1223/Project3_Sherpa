import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, FolderOpen, LogOut, User } from 'lucide-react'

function decodeTokenEmail() {
  const token = localStorage.getItem('auth_token')
  if (!token) return ''

  try {
    const payload = token.split('.')[1]
    const normalized = payload.replace(/-/g, '+').replace(/_/g, '/')
    const decoded = JSON.parse(window.atob(normalized))
    return decoded.sub || ''
  } catch {
    return ''
  }
}

export default function MyPage() {
  const navigate = useNavigate()
  const email = useMemo(() => decodeTokenEmail(), [])

  function handleLogout() {
    localStorage.removeItem('auth_token')
    navigate('/login')
  }

  return (
    <div style={styles.page}>
      <main style={styles.main}>
        <button type="button" style={styles.backButton} onClick={() => navigate('/board')}>
          <ArrowLeft size={17} /> 돌아가기
        </button>

        <section style={styles.panel}>
          <div style={styles.avatar}>
            <User size={28} />
          </div>
          <div>
            <p style={styles.eyebrow}>MY PAGE</p>
            <h1 style={styles.title}>마이페이지</h1>
            <p style={styles.subtitle}>{email || '로그인 정보가 없습니다.'}</p>
          </div>
        </section>

        <section style={styles.card}>
          <button type="button" style={styles.rowButton} onClick={() => navigate('/projects')}>
            <span style={styles.rowLeft}>
              <FolderOpen size={18} />
              내 프로젝트
            </span>
            <span style={styles.rowArrow}>›</span>
          </button>
          <button type="button" style={{ ...styles.rowButton, ...styles.logoutButton }} onClick={handleLogout}>
            <span style={styles.rowLeft}>
              <LogOut size={18} />
              로그아웃
            </span>
            <span style={styles.rowArrow}>›</span>
          </button>
        </section>
      </main>
    </div>
  )
}

const styles = {
  page: {
    minHeight: '100vh',
    background:
      'radial-gradient(1100px 600px at 12% -10%, rgba(124,92,234,0.10), transparent 60%), ' +
      'radial-gradient(900px 500px at 100% 10%, rgba(22,163,122,0.07), transparent 55%), ' +
      'radial-gradient(800px 500px at 50% 110%, rgba(224,96,61,0.06), transparent 55%), #faf8f4',
    color: '#1c1a2e',
    fontFamily: "'Pretendard', -apple-system, sans-serif",
    padding: '32px 20px',
  },
  main: {
    maxWidth: 640,
    margin: '0 auto',
  },
  backButton: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 7,
    marginBottom: 22,
    padding: '10px 14px',
    borderRadius: 12,
    border: '1px solid rgba(28,26,46,0.10)',
    background: 'rgba(255,255,255,0.72)',
    color: '#5b5770',
    cursor: 'pointer',
    fontSize: 14,
  },
  panel: {
    display: 'flex',
    alignItems: 'center',
    gap: 18,
    padding: 22,
    borderRadius: 16,
    border: '1px solid rgba(28,26,46,0.10)',
    background: 'rgba(255,255,255,0.72)',
    boxShadow: '0 2px 14px rgba(28,26,46,0.05)',
    backdropFilter: 'blur(14px)',
    marginBottom: 16,
  },
  avatar: {
    width: 58,
    height: 58,
    borderRadius: 18,
    background: 'rgba(124,92,234,0.12)',
    color: '#7c5cea',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  eyebrow: {
    margin: '0 0 4px',
    fontSize: 11,
    fontWeight: 700,
    color: '#7c5cea',
    letterSpacing: '0.08em',
  },
  title: {
    margin: 0,
    fontSize: 24,
    fontWeight: 700,
  },
  subtitle: {
    margin: '6px 0 0',
    fontSize: 13,
    color: '#918d9f',
  },
  card: {
    borderRadius: 16,
    border: '1px solid rgba(28,26,46,0.10)',
    background: 'rgba(255,255,255,0.72)',
    boxShadow: '0 2px 14px rgba(28,26,46,0.05)',
    backdropFilter: 'blur(14px)',
    overflow: 'hidden',
  },
  rowButton: {
    width: '100%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '17px 18px',
    border: 'none',
    borderBottom: '1px solid rgba(28,26,46,0.10)',
    background: 'transparent',
    color: '#1c1a2e',
    cursor: 'pointer',
    fontSize: 15,
    fontWeight: 600,
  },
  rowLeft: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 10,
  },
  rowArrow: {
    fontSize: 22,
    color: '#918d9f',
    lineHeight: 1,
  },
  logoutButton: {
    borderBottom: 'none',
    color: '#c05339',
  },
}
