import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { analyzeProject } from '../api/projectApi'
import MeetingChat from '../components/meeting/MeetingChat'

function downloadResultJson(result, projectId) {
  const blob = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${result.meeting_id || `analysis-${projectId}`}.json`
  a.click()
  URL.revokeObjectURL(url)
}

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
            ※ RAG 검색 + LangGraph + 실제 OpenAI 호출로 생성된 결과입니다(schema_version{' '}
            {result.schema_version}). 평가 대상 문서가 여러 개면 첫 번째 문서만 사용하며,
            분석/재평가마다 실제 API 비용이 발생합니다.
          </p>
          <MeetingChat result={result} />
          <details style={styles.card}>
            <summary style={styles.sectionTitle}>원본 JSON</summary>
            <button style={styles.downloadButton} onClick={() => downloadResultJson(result, projectId)}>
              .json 다운로드
            </button>
            <pre style={styles.pre}>{JSON.stringify(result, null, 2)}</pre>
          </details>
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
  downloadButton: {
    display: 'block',
    marginTop: 10,
    marginBottom: 10,
    padding: '6px 14px',
    fontSize: 13,
    color: '#2f7fd1',
    background: '#eaf3fb',
    border: '1px solid #cfe2f3',
    borderRadius: 8,
    cursor: 'pointer',
  },
  pre: {
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
    fontSize: 12,
    color: '#334',
    maxHeight: 480,
    overflow: 'auto',
  },
}
