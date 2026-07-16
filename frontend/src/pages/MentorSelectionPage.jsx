import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { getMentorCandidates, getProject } from '../api/projectApi'
import { docTypeLabel } from '../utils/docType'
import StepSidebar from '../components/wizard/StepSidebar'
import { useSimulatedProgress } from '../hooks/useSimulatedProgress'

// 가은/Claude(2026-07-16): STEP4 "공모전 분석" 화면 — 사용자가 준 목업(왼쪽 8단계
// 사이드바 / 가운데 성격분석+멘토추천 / 오른쪽 AI 어시스턴트+공모개요) 기반. 목업엔
// "심사위원"이라 써있지만 실제 라벨은 "멘토"로 쓰기로 함(사용자 확정). 사이드바는
// components/wizard/StepSidebar.jsx로 뺐다(FeedbackProgressPage와 공유, 클릭해서
// 화면 확인용으로 이동 가능).

const MIN_MENTORS = 2
const MAX_MENTORS = 4

export default function MentorSelectionPage() {
  const { projectId } = useParams()
  const navigate = useNavigate()
  const [project, setProject] = useState(null)
  const [candidates, setCandidates] = useState(null)
  const [selected, setSelected] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  // 가은/Claude(2026-07-16): "분석 시작"을 누르면 이 페이지로 넘어오면서 바로
  // getMentorCandidates()(실제 OpenAI 1회 호출)가 시작된다 — 그 진행 상황을 그냥
  // 텍스트 한 줄이 아니라 진행률 바로 보여달라는 요청. 딱 1건짜리 진행률이라
  // FeedbackProgressPage와 같은 useSimulatedProgress(count=1)를 재사용한다.
  const [progress, setProgress] = useSimulatedProgress(1)

  useEffect(() => {
    Promise.all([getProject(projectId), getMentorCandidates(projectId)])
      .then(([proj, data]) => {
        setProgress([100])
        setProject(proj)
        setCandidates(data)
        setLoading(false)
      })
      .catch((err) => {
        setError(err.message)
        setLoading(false)
      })
  }, [projectId])

  function toggleMentor(personaId) {
    setSelected((prev) => {
      if (prev.includes(personaId)) return prev.filter((id) => id !== personaId)
      if (prev.length >= MAX_MENTORS) return prev
      return [...prev, personaId]
    })
  }

  // 가은/Claude(2026-07-16): 원래 여기서 바로 analyzeProject()를 부르고 버튼 텍스트만
  // "피드백 준비 중..."으로 바꿨는데, 사용자 요청으로 STEP6 "피드백 진행" 전용 화면
  // (FeedbackProgressPage)을 분리했다 — 실제 analyze() 호출과 그 내부 진행(경이의
  // run_meeting())은 그 페이지로 옮기고, 여기서는 선택한 멘토 목록만 넘긴다.
  function handleStartFeedback() {
    const chosen = candidates.candidates.filter((c) => selected.includes(c.persona_id))
    navigate(`/projects/${projectId}/progress`, { state: { mentors: chosen } })
  }

  const canStart = selected.length >= MIN_MENTORS && selected.length <= MAX_MENTORS

  return (
    <div style={styles.page}>
      <StepSidebar projectId={projectId} activeIndex={2} />

      <main style={styles.main}>
        <div style={styles.stepLabel}>STEP 3 / 7</div>
        <h1 style={styles.title}>공모전 분석</h1>

        {loading && (
          <div style={styles.progressBox}>
            <p style={styles.muted}>문서 성격을 분석하고 어울리는 멘토를 찾는 중...</p>
            <div style={styles.progressTrack}>
              <div style={{ ...styles.progressFill, width: `${progress[0] || 0}%` }} />
            </div>
            <p style={styles.progressPercent}>{Math.round(progress[0] || 0)}%</p>
          </div>
        )}
        {error && <p style={styles.error}>{error}</p>}

        {candidates && (
          <>
            <div style={styles.sectionLabel}>공모전 성격 분석</div>
            <div style={styles.tagRow}>
              {candidates.characteristics.map((tag) => (
                <span key={tag} style={styles.tag}>
                  {tag}
                </span>
              ))}
            </div>

            <div style={styles.sectionLabel}>
              추천 멘토 · 공모전 성격에 맞춰 {candidates.candidates.length}명을 추천했어요
            </div>
            {/* 가은/Claude(2026-07-16, 수정 필요): 카드에 쓰는 display_name/role은
                get_mentor_candidates()가 ai/meeting/personas/persona_cards.json에서 그대로
                읽어온 값이다(persona_cards.json의 display_name은 "사업전략 전문가"처럼
                "전문가"로 끝나서, 여기 화면 라벨("멘토")과 안 어울린다 — 예: "사업전략
                전문가 멘토"). persona_cards.json 쪽 표기를 "멘토" 톤으로 바꿀지, 아니면
                여기서 표시할 때만 문자열을 다듬을지 아직 안 정했다. 아바타도 색 원 placeholder
                뿐이라 실제 이미지/아이콘 붙이는 것도 남음. */}
            <div style={styles.candidateGrid}>
              {candidates.candidates.map((c) => {
                const isSelected = selected.includes(c.persona_id)
                return (
                  <button
                    key={c.persona_id}
                    style={{ ...styles.candidateCard, ...(isSelected ? styles.candidateCardSelected : {}) }}
                    onClick={() => toggleMentor(c.persona_id)}
                  >
                    {isSelected && <span style={styles.candidateCheck}>✓</span>}
                    <div style={styles.candidateAvatar} />
                    <div style={styles.candidateName}>{c.display_name} 멘토</div>
                    <span style={styles.candidateTag}>{c.fit_tag}</span>
                  </button>
                )
              })}
            </div>

            <button style={styles.startButton} onClick={handleStartFeedback} disabled={!canStart}>
              멘토 선택하기 ({selected.length}/{MAX_MENTORS}) →
            </button>
            {!canStart && <p style={styles.helperText}>멘토를 2~4명 선택해주세요.</p>}
          </>
        )}
      </main>

      <aside style={styles.assistantPanel}>
        <div style={styles.assistantBubbleRow}>
          <div style={styles.assistantIcon}>✨</div>
          <div style={styles.assistantBubble}>
            공모전 성격을 분석해서 어울리는 멘토 2~4명을 추천했어요. 태그를 눌러 상세 기준도
            볼 수 있어요.
          </div>
        </div>

        {project && (
          <div style={styles.overviewBox}>
            <div style={styles.overviewTitle}>공모 개요</div>
            <div style={styles.overviewRow}>
              <span style={styles.overviewLabel}>공모전명</span>
              <span style={styles.overviewValue}>{project.title}</span>
            </div>
            <div style={styles.overviewRow}>
              <span style={styles.overviewLabel}>공모 분야</span>
              <span style={styles.overviewValue}>{docTypeLabel(project.doc_type)}</span>
            </div>
            <div style={styles.overviewRow}>
              <span style={styles.overviewLabel}>마감일</span>
              <span style={styles.overviewValue}>미정</span>
            </div>
          </div>
        )}
      </aside>
    </div>
  )
}

const ACCENT = '#7c4dff'

const styles = {
  page: {
    minHeight: '100vh',
    display: 'grid',
    gridTemplateColumns: '260px 1fr 300px',
    background: '#f7f7fb',
    color: '#1f2333',
  },
  main: { padding: '24px 32px', overflowY: 'auto' },
  stepLabel: { fontSize: 12, fontWeight: 700, color: ACCENT, letterSpacing: 0.5 },
  title: { fontSize: 22, fontWeight: 700, margin: '4px 0 20px' },
  muted: { color: '#8b8fa3' },
  progressBox: { maxWidth: 360, marginBottom: 20 },
  progressTrack: { height: 6, borderRadius: 999, background: '#f0eefc', overflow: 'hidden', marginTop: 8 },
  progressFill: { height: '100%', borderRadius: 999, background: ACCENT, transition: 'width 0.5s ease' },
  progressPercent: { fontSize: 12, fontWeight: 700, color: '#8b8fa3', marginTop: 6 },
  error: { color: '#d64545' },
  sectionLabel: { fontSize: 13, fontWeight: 700, color: '#4b4f63', margin: '20px 0 10px' },
  tagRow: { display: 'flex', flexWrap: 'wrap', gap: 8 },
  tag: {
    fontSize: 12,
    fontWeight: 600,
    color: '#4b4f63',
    background: '#eef0f7',
    padding: '6px 12px',
    borderRadius: 999,
  },
  candidateGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(2, minmax(180px, 1fr))',
    gap: 14,
  },
  candidateCard: {
    position: 'relative',
    textAlign: 'left',
    background: '#fff',
    border: '1.5px solid #e5e3f0',
    borderRadius: 14,
    padding: 16,
    cursor: 'pointer',
    font: 'inherit',
    color: 'inherit',
  },
  candidateCardSelected: {
    borderColor: ACCENT,
    boxShadow: `0 0 0 3px ${ACCENT}22`,
  },
  candidateCheck: {
    position: 'absolute',
    top: 10,
    right: 10,
    width: 20,
    height: 20,
    borderRadius: '50%',
    background: ACCENT,
    color: '#fff',
    fontSize: 12,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
  candidateAvatar: {
    width: 48,
    height: 48,
    borderRadius: '50%',
    background: `${ACCENT}22`,
    marginBottom: 10,
  },
  candidateName: { fontSize: 14, fontWeight: 700, marginBottom: 8 },
  candidateTag: {
    display: 'inline-block',
    fontSize: 11,
    fontWeight: 600,
    color: ACCENT,
    background: `${ACCENT}15`,
    padding: '4px 9px',
    borderRadius: 999,
  },
  startButton: {
    display: 'block',
    width: '100%',
    marginTop: 24,
    padding: '14px 0',
    borderRadius: 12,
    border: 'none',
    background: ACCENT,
    color: '#fff',
    fontSize: 14,
    fontWeight: 700,
    cursor: 'pointer',
  },
  helperText: { marginTop: 8, fontSize: 12, color: '#8b8fa3', textAlign: 'center' },
  assistantPanel: {
    borderLeft: '1px solid #ece9f7',
    padding: '20px 16px',
  },
  assistantBubbleRow: { display: 'flex', gap: 10, marginBottom: 20 },
  assistantIcon: {
    width: 28,
    height: 28,
    borderRadius: '50%',
    background: ACCENT,
    color: '#fff',
    fontSize: 13,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  assistantBubble: {
    background: '#fff',
    border: '1px solid #ece9f7',
    borderRadius: 12,
    padding: 12,
    fontSize: 12.5,
    lineHeight: 1.6,
    color: '#4b4f63',
  },
  overviewBox: {
    background: '#fff',
    border: '1px solid #ece9f7',
    borderRadius: 12,
    padding: 14,
  },
  overviewTitle: { fontSize: 12, fontWeight: 700, color: '#8b8fa3', marginBottom: 10 },
  overviewRow: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: 12.5,
    padding: '6px 0',
    borderTop: '1px solid #f2f1f8',
  },
  overviewLabel: { color: '#8b8fa3' },
  overviewValue: { fontWeight: 600, color: '#1f2333' },
}
