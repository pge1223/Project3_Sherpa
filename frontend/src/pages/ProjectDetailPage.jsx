import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
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
  const navigate = useNavigate()
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  // 재인/Claude (2026-07-16): StrictMode 개발 모드는 마운트 시 이 useEffect를 두 번
  // 실행하는데, 아래 sessionStorage 캐시 체크는 analyzeProject()가 끝나기 전에 이뤄져서
  // 가드가 없으면 진짜 /analyze 요청(LLM 호출 포함, 실제 비용 발생)이 두 번 나간다.
  // 그 결과 setResult가 서로 다른 응답으로 두 번 불려서 result.media_script 참조가
  // 바뀌고, CommitteeVideoStage.jsx가 재생 중이던 위원 영상 스트림을 끊고 처음부터
  // 다시 요청하는 문제로 실제 관측됨 - projectId당 한 번만 요청하도록 ref로 막는다.
  const requestedProjectIdRef = useRef(null)

  useEffect(() => {
    const cached = sessionStorage.getItem(`analysis:${projectId}`)
    if (cached) {
      setResult(JSON.parse(cached))
      setLoading(false)
      return
    }

    if (requestedProjectIdRef.current === projectId) return
    requestedProjectIdRef.current = projectId

    analyzeProject(projectId)
      .then((data) => {
        sessionStorage.setItem(`analysis:${projectId}`, JSON.stringify(data))
        setResult(data)
        setLoading(false)
      })
      .catch((err) => {
        setError(err.message)
        setLoading(false)
        requestedProjectIdRef.current = null // 실패 시 재시도 가능하도록 가드 해제
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
          {/* 가은/Claude (2026-07-17): 위원 영상 시뮬레이션 전용 페이지(/simulation)는
              없앴다 — CommitteeVideoStage.jsx(재인님 파일, 안 건드림)를 STEP7
              "대화형 피드백"(/feedback-chat) 화면 상단으로 옮기고 그 아래 대화창을
              붙였다(사용자 요청). 여기서는 그 화면으로 가는 링크만 둔다. */}
          <button style={styles.simulationButton} onClick={() => navigate(`/projects/${projectId}/feedback-chat`)}>
            🎬 회의 영상 · 대화형 피드백으로 보기
          </button>
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
  simulationButton: {
    display: 'block',
    margin: '16px 0',
    padding: '10px 18px',
    fontSize: 14,
    fontWeight: 600,
    color: '#fff',
    background: '#1a3a5c',
    border: 'none',
    borderRadius: 999,
    cursor: 'pointer',
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
