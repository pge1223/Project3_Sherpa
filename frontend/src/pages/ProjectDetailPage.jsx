import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { analyzeProject } from '../api/projectApi'

export default function ProjectDetailPage() {
  const { projectId } = useParams()
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const cached = sessionStorage.getItem(`analysis:${projectId}`)
    if (cached) {
      setResult(JSON.parse(cached))
      setLoading(false)
      return
    }

    analyzeProject(projectId)
      .then((data) => {
        sessionStorage.setItem(`analysis:${projectId}`, JSON.stringify(data))
        setResult(data)
        setLoading(false)
      })
      .catch((err) => {
        setError(err.message)
        setLoading(false)
      })
  }, [projectId])

  return (
    <div style={styles.page}>
      <h1 style={styles.title}>프로젝트 상세: {projectId}</h1>

      {loading && <p style={styles.muted}>분석 결과를 불러오는 중...</p>}
      {error && <p style={styles.error}>{error}</p>}

      {result && (
        <>
          <p style={styles.mockNotice}>
            ※ 현재 위원회 그래프(M4)가 아직 준비되지 않아, 계약(schema_version {result.schema_version}) 형태의
            mock 결과를 보여주고 있습니다.
          </p>
          {result.chair_summary && (
            <div style={styles.card}>
              <h2 style={styles.sectionTitle}>위원장 종합</h2>
              <p>{result.chair_summary.summary_text || JSON.stringify(result.chair_summary)}</p>
            </div>
          )}
          <div style={styles.card}>
            <h2 style={styles.sectionTitle}>원본 JSON</h2>
            <pre style={styles.pre}>{JSON.stringify(result, null, 2)}</pre>
          </div>
        </>
      )}
    </div>
  )
}

const styles = {
  page: {
    minHeight: '100vh',
    background: 'linear-gradient(180deg, #dceefc 0%, #eaf3fb 100%)',
    color: '#17324a',
    padding: 48,
  },
  title: { color: '#1a3a5c' },
  muted: { color: '#7994ac' },
  error: { color: '#d64545' },
  mockNotice: {
    fontSize: 13,
    color: '#9a6400',
    background: '#fdf1d6',
    padding: '10px 14px',
    borderRadius: 8,
    display: 'inline-block',
  },
  card: {
    background: '#fff',
    border: '1px solid #d9e8f5',
    borderRadius: 12,
    padding: 20,
    marginTop: 16,
  },
  sectionTitle: { margin: '0 0 10px', fontSize: 16, color: '#1a3a5c' },
  pre: {
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
    fontSize: 12,
    color: '#334',
    maxHeight: 480,
    overflow: 'auto',
  },
}
