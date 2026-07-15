import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getProjects } from '../api/projectApi'
import StatusBadge from '../components/common/StatusBadge'
import SpaceBackground from '../components/landing/SpaceBackground'

function FolderIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#5c86ac" strokeWidth="1.8">
      <path d="M3 6.5C3 5.67 3.67 5 4.5 5h4.4c.35 0 .68.14.93.38L11 6.5h8.5c.83 0 1.5.67 1.5 1.5v9.5c0 .83-.67 1.5-1.5 1.5h-15C3.67 19 3 18.33 3 17.5v-11Z" />
    </svg>
  )
}

function ChevronIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#93aec5" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 6l6 6-6 6" />
    </svg>
  )
}

export default function ProjectListPage() {
  const navigate = useNavigate()
  const [projects, setProjects] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    getProjects()
      .then((data) => {
        setProjects(data)
        setLoading(false)
      })
      .catch((err) => {
        setError(err.message)
        setLoading(false)
      })
  }, [])

  return (
    <div style={styles.page}>
      <SpaceBackground />
      <div style={styles.pageInner}>
        <img src="/images/logo4.png" alt="AI Review Board" style={styles.logo} />

        <div style={styles.card}>
        <div style={styles.header}>
          <h1 style={styles.title}>내 프로젝트</h1>
          <button style={styles.newButton} onClick={() => navigate('/projects/new')}>
            + 새 프로젝트
          </button>
        </div>

        <div style={styles.divider} />

        {loading && <p style={styles.empty}>불러오는 중...</p>}
        {!loading && error && <p style={styles.empty}>{error}</p>}
        {!loading && !error && projects.length === 0 && <p style={styles.empty}>아직 프로젝트가 없습니다.</p>}

        {!error && projects.map((project, i) => (
          <div
            key={project.id}
            style={{
              ...styles.row,
              borderBottom: i === projects.length - 1 ? 'none' : '1px solid #e2edf7',
            }}
            onClick={() => navigate(`/projects/${project.id}`)}
          >
            <div style={styles.rowLeft}>
              <FolderIcon />
              <div>
                <div style={styles.rowTitle}>{project.title}</div>
                <div style={styles.rowDate}>{String(project.created_at).slice(0, 10)} 생성</div>
              </div>
            </div>
            <div style={styles.rowRight}>
              <StatusBadge status={project.status} />
              <ChevronIcon />
            </div>
          </div>
        ))}
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
    padding: '48px 24px',
    display: 'flex',
    justifyContent: 'center',
  },
  pageInner: {
    position: 'relative',
    zIndex: 2,
    width: '100%',
    maxWidth: 720,
  },
  logo: {
    display: 'block',
    width: 240,
    height: 'auto',
    margin: '0 auto 20px',
  },
  card: {
    width: '100%',
    background: '#fff',
    border: '1px solid #d9e8f5',
    borderRadius: 16,
    boxShadow: '0 8px 24px rgba(43, 111, 178, 0.10)',
    padding: 24,
    height: 'fit-content',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  title: {
    margin: 0,
    fontSize: 18,
    fontWeight: 700,
    color: '#1a3a5c',
  },
  newButton: {
    padding: '8px 16px',
    borderRadius: 999,
    background: '#2f7fd1',
    border: 'none',
    color: '#fff',
    fontSize: 13,
    fontWeight: 500,
    cursor: 'pointer',
  },
  divider: {
    borderTop: '1px solid #e2edf7',
    margin: '16px 0',
  },
  empty: {
    color: '#7994ac',
    fontSize: 14,
    padding: '24px 0',
    textAlign: 'center',
  },
  row: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '16px 4px',
    cursor: 'pointer',
  },
  rowLeft: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
  },
  rowTitle: {
    fontSize: 15,
    fontWeight: 600,
    color: '#17324a',
  },
  rowDate: {
    fontSize: 13,
    color: '#7994ac',
    marginTop: 4,
  },
  rowRight: {
    display: 'flex',
    alignItems: 'center',
    gap: 14,
  },
}
