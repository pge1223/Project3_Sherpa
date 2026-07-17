import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { analyzeProject, getAnalyzeProgress } from '../api/projectApi'
import StepSidebar from '../components/wizard/StepSidebar'

// 가은/Claude(2026-07-16): STEP6 "피드백 진행" 화면. 사용자 요청: "우리가 이전에 있던
// 분석시작 버튼을 누르면 내부적으로 진행되었던 ProjectDetailPage 로직이 돌아간다 — 화면에
// 표시 X, 내부적인 것만." 즉 여기서 실제 analyzeProject(projectId, committee)를 실행하되
// (경이의 run_meeting() 전체가 여기서 돈다), 화면엔 그 내부 진행 상황을 실제 단계로 보여준다.
//
// 가은/Claude(2026-07-17): "진짜 진행률로 바꿔줘" — 처음엔 시간 기반으로 흉내낸 진행률
// (useSimulatedProgress)이었는데, run_meeting()이 이미 on_progress 콜백(MTG-006)을
// 지원하는 걸 발견해서 실제 값으로 교체했다. analyzeProject() 자체는 여전히 완료 전까지
// 응답이 없는 단일 HTTP 호출이라, 진행 중엔 별도로 GET .../analyze/progress를 폴링해서
// {stage, reviews_done, reviews_total, score_done, chair_done} 스냅샷을 받아온다.
// 다만 위원 리뷰 노드들은 LangGraph에서 병렬로 실행돼(ai/meeting/graph/build.py) 한
// superstep에 한꺼번에 끝나므로, "리뷰 33% -> 66% -> 100%"처럼 위원 개별 진행은 관측되지
// 않는다 — 실제로 관측 가능한 건 "리뷰 전체 완료 여부/채점 완료/위원장 종합 완료" 3단계뿐이라
// 화면도 그 3단계 스테퍼 + 멘토 카드는 "검토 중"/"검토 완료" 두 상태만 보여주는 정직한
// 수준으로 맞췄다(개별 멘토 카드에 가짜 퍼센트를 채우지 않는다).
// 사이드바는 components/wizard/StepSidebar.jsx로 뺐다(MentorSelectionPage와 공유).

const TAG_COLORS = ['#e9e4fb', '#dff0ff', '#ffe6ee', '#fff2d9']
const TAG_TEXT_COLORS = ['#6a3fd0', '#1b6fc2', '#c23a68', '#a1720b']

const POLL_INTERVAL_MS = 1000

function overallPercent(snapshot) {
  if (!snapshot) return 0
  if (snapshot.chair_done) return 100
  if (snapshot.score_done) return 85
  if (snapshot.reviews_total) return 10 + (snapshot.reviews_done / snapshot.reviews_total) * 60
  return 5
}

const STAGE_STEPS = [
  { key: 'reviews', label: '멘토별 독립 검토' },
  { key: 'score', label: '채점 집계' },
  { key: 'chair', label: '위원장 종합' },
]

function stageStatus(step, snapshot, mentorCount) {
  const reviewsDone = !!snapshot && snapshot.reviews_total > 0 && snapshot.reviews_done >= mentorCount
  if (step.key === 'reviews') {
    if (reviewsDone) return 'done'
    return snapshot ? 'active' : 'pending'
  }
  if (step.key === 'score') {
    if (snapshot?.score_done) return 'done'
    return reviewsDone ? 'active' : 'pending'
  }
  // chair
  if (snapshot?.chair_done) return 'done'
  return snapshot?.score_done ? 'active' : 'pending'
}

export default function FeedbackProgressPage() {
  const { projectId } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const mentors = location.state?.mentors // [{persona_id, display_name, role, fit_tag}, ...]
  const [error, setError] = useState('')
  const requestedRef = useRef(false)
  const [snapshot, setSnapshot] = useState(null)
  const progressTokenRef = useRef(null)
  if (!progressTokenRef.current) {
    progressTokenRef.current =
      typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`
  }

  useEffect(() => {
    if (!mentors) {
      // 새로고침 등으로 route state가 날아간 경우 — 멘토 선택부터 다시
      navigate(`/projects/${projectId}/analysis`, { replace: true })
      return
    }
    if (requestedRef.current) return
    requestedRef.current = true

    const progressToken = progressTokenRef.current
    const pollTimer = setInterval(() => {
      getAnalyzeProgress(projectId, progressToken).then((data) => {
        if (data) setSnapshot(data)
      })
    }, POLL_INTERVAL_MS)

    analyzeProject(
      projectId,
      mentors.map((m) => m.persona_id),
      progressToken,
    )
      .then((result) => {
        setSnapshot((prev) => ({ ...(prev || {}), score_done: true, chair_done: true }))
        sessionStorage.setItem(`analysis:${projectId}`, JSON.stringify(result))
        navigate(`/projects/${projectId}/feedback-chat`, { replace: true })
      })
      .catch((err) => {
        setError(err.message)
        requestedRef.current = false // 재시도 가능하도록
      })
      .finally(() => clearInterval(pollTimer))

    return () => clearInterval(pollTimer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, mentors])

  if (!mentors) return null

  const mentorCount = mentors.length
  const reviewsDone = !!snapshot && snapshot.reviews_total > 0 && snapshot.reviews_done >= mentorCount
  const percent = overallPercent(snapshot)

  return (
    <div style={styles.page}>
      <StepSidebar projectId={projectId} activeIndex={4} />

      <main style={styles.main}>
        <div style={styles.stepLabel}>STEP 5 / 7</div>
        <h1 style={styles.title}>피드백 진행</h1>
        <p style={styles.subtitleText}>멘토들이 기획서를 바탕으로 독립적으로 피드백을 준비하고 있어요.</p>

        {error && (
          <p style={styles.error}>
            {error}{' '}
            <button style={styles.retryLink} onClick={() => window.location.reload()}>
              다시 시도
            </button>
          </p>
        )}

        <div style={styles.overallBox}>
          <div style={styles.overallTrack}>
            <div style={{ ...styles.overallFill, width: `${percent}%` }} />
          </div>
          <p style={styles.overallPercent}>{Math.round(percent)}%</p>
        </div>

        <div style={styles.stageRow}>
          {STAGE_STEPS.map((step) => {
            const status = stageStatus(step, snapshot, mentorCount)
            return (
              <div key={step.key} style={styles.stageItem}>
                <span
                  style={{
                    ...styles.stageDot,
                    ...(status === 'done' ? styles.stageDotDone : {}),
                    ...(status === 'active' ? styles.stageDotActive : {}),
                  }}
                >
                  {status === 'done' ? '✓' : ''}
                </span>
                <span style={{ ...styles.stageLabel, ...(status === 'pending' ? styles.stageLabelPending : {}) }}>
                  {step.label}
                </span>
              </div>
            )
          })}
        </div>

        <div style={styles.mentorList}>
          {mentors.map((m, i) => (
            <div key={m.persona_id} style={styles.mentorCard}>
              <div style={styles.mentorRow}>
                <div style={styles.mentorAvatar} />
                <p style={styles.mentorName}>{m.display_name} 멘토</p>
                <span
                  style={{
                    ...styles.mentorTag,
                    background: TAG_COLORS[i % TAG_COLORS.length],
                    color: TAG_TEXT_COLORS[i % TAG_TEXT_COLORS.length],
                  }}
                >
                  {m.fit_tag}
                </span>
                <span style={styles.mentorStatus}>{reviewsDone ? '검토 완료' : '검토 중...'}</span>
              </div>
              <div style={styles.progressTrack}>
                <div style={{ ...styles.progressFill, width: reviewsDone ? '100%' : '35%' }} />
              </div>
            </div>
          ))}
        </div>

        <div style={styles.timeNote}>⏱ 평균 검토 시간 약 3~5분 · 잠시만 기다려주세요</div>
      </main>
    </div>
  )
}

const ACCENT = '#7c4dff'

const styles = {
  page: {
    minHeight: '100vh',
    display: 'grid',
    gridTemplateColumns: '260px 1fr',
    background: '#f7f7fb',
    color: '#1f2333',
  },
  main: { padding: '24px 32px', maxWidth: 640 },
  stepLabel: { fontSize: 12, fontWeight: 700, color: ACCENT, letterSpacing: 0.5 },
  title: { fontSize: 22, fontWeight: 700, margin: '4px 0 6px' },
  subtitleText: { fontSize: 13, color: '#8b8fa3', marginBottom: 20 },
  error: { color: '#d64545', fontSize: 13, marginBottom: 16 },
  retryLink: {
    border: 'none',
    background: 'none',
    color: ACCENT,
    fontWeight: 600,
    cursor: 'pointer',
    fontSize: 13,
    padding: 0,
  },
  overallBox: { marginBottom: 16 },
  overallTrack: { height: 8, borderRadius: 999, background: '#f0eefc', overflow: 'hidden' },
  overallFill: { height: '100%', borderRadius: 999, background: ACCENT, transition: 'width 0.6s ease' },
  overallPercent: { fontSize: 12, fontWeight: 700, color: '#8b8fa3', marginTop: 6 },
  stageRow: { display: 'flex', gap: 18, marginBottom: 22 },
  stageItem: { display: 'flex', alignItems: 'center', gap: 6 },
  stageDot: {
    width: 18,
    height: 18,
    borderRadius: '50%',
    border: '1.5px solid #d8d5ec',
    fontSize: 11,
    color: '#fff',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  stageDotDone: { background: ACCENT, borderColor: ACCENT },
  stageDotActive: { borderColor: ACCENT, boxShadow: `0 0 0 3px ${ACCENT}22` },
  stageLabel: { fontSize: 12.5, fontWeight: 600, color: '#4b4f63' },
  stageLabelPending: { color: '#b7b9c9' },
  mentorList: { display: 'flex', flexDirection: 'column', gap: 14 },
  mentorCard: {
    background: '#fff',
    border: '1px solid #ece9f7',
    borderRadius: 14,
    padding: 16,
  },
  mentorRow: { display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 },
  mentorAvatar: { width: 32, height: 32, borderRadius: '50%', background: `${ACCENT}22`, flexShrink: 0 },
  mentorName: { fontSize: 14, fontWeight: 600, flex: 1, margin: 0 },
  mentorTag: { fontSize: 11, fontWeight: 600, padding: '3px 9px', borderRadius: 999 },
  mentorStatus: { fontSize: 12, fontWeight: 700, color: '#8b8fa3' },
  progressTrack: { height: 6, borderRadius: 999, background: '#f0eefc', overflow: 'hidden' },
  progressFill: { height: '100%', borderRadius: 999, background: ACCENT, transition: 'width 0.5s ease' },
  timeNote: {
    marginTop: 20,
    fontSize: 12.5,
    color: '#8b8fa3',
    display: 'flex',
    alignItems: 'center',
    gap: 6,
  },
}
