import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { analyzeProject, getAnalyzeProgress, getMentorCandidates, getProject } from '../api/projectApi'
import { docTypeLabel } from '../utils/docType'
import StepSidebar from '../components/wizard/StepSidebar'
import { useSimulatedProgress } from '../hooks/useSimulatedProgress'

// 가은/Claude(2026-07-16): STEP4 "공모전 분석" 화면 — 사용자가 준 목업(왼쪽 8단계
// 사이드바 / 가운데 성격분석+멘토추천 / 오른쪽 AI 어시스턴트+공모개요) 기반. 목업엔
// "심사위원"이라 써있지만 실제 라벨은 "멘토"로 쓰기로 함(사용자 확정). 사이드바는
// components/wizard/StepSidebar.jsx로 뺐다(FeedbackProgressPage와 공유, 클릭해서
// 화면 확인용으로 이동 가능).
//
// 가은/Claude(2026-07-17): 사용자 요청으로 별도 화면이었던 "피드백 진행"
// (FeedbackProgressPage)을 이 화면에 합쳤다 — "멘토링 준비" 버튼을 누르면 같은
// 화면 안에서 바로 아래에 진행 상황(퍼센트 바 + 3단계 스테퍼 + 멘토별 검토 상태)이
// 뜬다. 진행률 폴링/스테이지 판정 로직은 FeedbackProgressPage에서 그대로 옮겨왔다.
//
// 가은/Claude(2026-07-17, 경이와 조율): 위원장 종합을 백그라운드로 분리하면서, 멘토
// 검토(+채점)만 끝나면 "회의 시작" 버튼이 나타난다 — 이걸 눌러야 대화형 피드백으로
// 이동한다(자동 이동 아님). 위원장은 그 사이 백그라운드에서 계속 종합 중이며, 대화형
// 피드백 화면 진입 시점엔 멘토 발언만 보인다(chair_summary가 아직 null이라
// meetingTheme.js의 buildTranscript()가 자동으로 위원장 오프닝 버블을 생략함).

const MIN_MENTORS = 2
const MAX_MENTORS = 4
const POLL_INTERVAL_MS = 1000

const STAGE_STEPS = [
  { key: 'reviews', label: '멘토별 독립 검토' },
  { key: 'score', label: '채점 집계' },
  { key: 'chair', label: '위원장 종합' },
]

function overallPercent(snapshot) {
  if (!snapshot) return 0
  if (snapshot.chair_done) return 100
  if (snapshot.score_done) return 85
  if (snapshot.reviews_total) return 10 + (snapshot.reviews_done / snapshot.reviews_total) * 60
  return 5
}

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

  // 가은/Claude(2026-07-17): 여기부터는 옛 FeedbackProgressPage의 상태 — "멘토링
  // 준비" 버튼을 누른 뒤 실제 analyzeProject() 진행 상황을 이 화면에서 바로 보여준다.
  const [analyzing, setAnalyzing] = useState(false)
  const [analyzeError, setAnalyzeError] = useState('')
  const [snapshot, setSnapshot] = useState(null)
  const progressTokenRef = useRef(null)
  // 가은/Claude(2026-07-17, 경이와 조율): 위원장 종합을 백그라운드로 미루기로 하면서
  // analyzeProject()가 이제 리뷰+채점만 끝나면 resolve된다 — resolve됐다고 바로
  // 대화형 피드백으로 넘기지 않고, "회의 시작" 버튼을 보여준 뒤 사용자가 직접 눌러야
  // 이동한다. reviewsReady가 그 상태를 나타낸다.
  const [reviewsReady, setReviewsReady] = useState(false)
  const pollTimerRef = useRef(null)

  useEffect(() => {
    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current)
    }
  }, [])

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
  // (FeedbackProgressPage)을 분리했었다.
  // 가은/Claude(2026-07-17): 사용자가 다시 "화면 하나로 합치자"고 요청 — 이제 이
  // 화면에서 바로 analyzeProject()를 실행하고 진행 상황도 이 화면 안에서 보여준다
  // (FeedbackProgressPage에 있던 폴링 로직 그대로).
  const chosenMentors = candidates ? candidates.candidates.filter((c) => selected.includes(c.persona_id)) : []

  function handleStartFeedback() {
    if (analyzing) return
    if (!progressTokenRef.current) {
      progressTokenRef.current =
        typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`
    }
    const progressToken = progressTokenRef.current
    setAnalyzeError('')
    setSnapshot(null)
    setReviewsReady(false)
    setAnalyzing(true)

    // 가은/Claude(2026-07-17): 이전엔 analyzeProject()가 resolve되는 시점(=위원장까지
    // 전부 끝난 시점)에 맞춰 .finally()에서 폴링을 끊었다. 이제 리뷰만 끝나도
    // resolve되고 위원장은 백그라운드에서 계속 도니, 폴링은 resolve와 무관하게
    // chair_done이 true가 될 때까지(또는 언마운트될 때까지) 계속 돌려서 "위원장 종합"
    // 스테퍼가 백그라운드 진행 상황을 정직하게 반영하게 한다.
    pollTimerRef.current = setInterval(() => {
      getAnalyzeProgress(projectId, progressToken).then((data) => {
        if (!data) return
        setSnapshot(data)
        if (data.chair_done && pollTimerRef.current) {
          clearInterval(pollTimerRef.current)
          pollTimerRef.current = null
        }
      })
    }, POLL_INTERVAL_MS)

    analyzeProject(
      projectId,
      chosenMentors.map((m) => m.persona_id),
      progressToken,
    )
      .then((result) => {
        sessionStorage.setItem(`analysis:${projectId}`, JSON.stringify(result))
        setReviewsReady(true)
      })
      .catch((err) => {
        setAnalyzeError(err.message)
        setAnalyzing(false) // 재시도 가능하도록
        progressTokenRef.current = null
        if (pollTimerRef.current) {
          clearInterval(pollTimerRef.current)
          pollTimerRef.current = null
        }
      })
  }

  const canStart = selected.length >= MIN_MENTORS && selected.length <= MAX_MENTORS
  const mentorCount = chosenMentors.length
  const reviewsDone = !!snapshot && snapshot.reviews_total > 0 && snapshot.reviews_done >= mentorCount
  const analyzePercent = overallPercent(snapshot)

  return (
    <div style={styles.page}>
      <StepSidebar projectId={projectId} activeIndex={2} />

      <main style={styles.main}>
        <div style={styles.stepLabel}>STEP 3 / 5</div>
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
                    disabled={analyzing}
                  >
                    {isSelected && <span style={styles.candidateCheck}>✓</span>}
                    <div style={styles.candidateAvatar} />
                    <div style={styles.candidateName}>{c.display_name} 멘토</div>
                    <span style={styles.candidateTag}>{c.fit_tag}</span>
                  </button>
                )
              })}
            </div>

            <button style={styles.startButton} onClick={handleStartFeedback} disabled={!canStart || analyzing}>
              멘토링 준비 ({selected.length}/{MAX_MENTORS}) →
            </button>
            {!canStart && !analyzing && <p style={styles.helperText}>멘토를 2~4명 선택해주세요.</p>}

            {analyzeError && (
              <p style={styles.error}>
                {analyzeError}{' '}
                <button style={styles.retryLink} onClick={handleStartFeedback}>
                  다시 시도
                </button>
              </p>
            )}

            {/* 가은/Claude(2026-07-17): "멘토링 준비"를 누르면 바로 아래에 진행 상황이
                뜬다 — 옛 FeedbackProgressPage의 진행률 바 + 3단계 스테퍼 + 멘토별
                검토 상태 카드를 그대로 옮겨왔다. 리뷰(+채점)만 끝나면(위원장 종합은
                아직) reviewsReady가 true가 되어 "회의 시작" 버튼이 나타난다. */}
            {analyzing && (
              <div style={styles.analyzeBox}>
                <p style={styles.subtitleText}>멘토들이 기획서를 바탕으로 독립적으로 피드백을 준비하고 있어요.</p>

                <div style={styles.overallBox}>
                  <div style={styles.overallTrack}>
                    <div style={{ ...styles.overallFill, width: `${analyzePercent}%` }} />
                  </div>
                  <p style={styles.overallPercent}>{Math.round(analyzePercent)}%</p>
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
                        <span
                          style={{ ...styles.stageLabel, ...(status === 'pending' ? styles.stageLabelPending : {}) }}
                        >
                          {step.label}
                        </span>
                      </div>
                    )
                  })}
                </div>

                <div style={styles.mentorList}>
                  {chosenMentors.map((m) => (
                    <div key={m.persona_id} style={styles.mentorCard}>
                      <div style={styles.mentorRow}>
                        <div style={styles.mentorAvatar} />
                        <p style={styles.mentorName}>{m.display_name} 멘토</p>
                        <span style={styles.mentorStatus}>{reviewsDone ? '검토 완료' : '검토 중...'}</span>
                      </div>
                      <div style={styles.progressTrack}>
                        <div style={{ ...styles.progressFill, width: reviewsDone ? '100%' : '35%' }} />
                      </div>
                    </div>
                  ))}
                </div>

                {!reviewsReady && (
                  <div style={styles.timeNote}>⏱ 평균 검토 시간 약 3~5분 · 잠시만 기다려주세요</div>
                )}

                {reviewsReady && (
                  <>
                    <p style={styles.timeNote}>
                      멘토들의 검토가 끝났어요. 위원장 종합은 백그라운드에서 계속 진행돼요 —
                      대화 중 필요할 때 참고할게요.
                    </p>
                    <button
                      style={styles.startButton}
                      onClick={() => navigate(`/projects/${projectId}/feedback-chat`)}
                    >
                      회의 시작 →
                    </button>
                  </>
                )}
              </div>
            )}
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
  retryLink: {
    border: 'none',
    background: 'none',
    color: ACCENT,
    fontWeight: 600,
    cursor: 'pointer',
    fontSize: 13,
    padding: 0,
  },
  analyzeBox: { marginTop: 24, maxWidth: 480 },
  subtitleText: { fontSize: 13, color: '#8b8fa3', marginBottom: 16 },
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
  mentorStatus: { fontSize: 12, fontWeight: 700, color: '#8b8fa3' },
  timeNote: {
    marginTop: 20,
    fontSize: 12.5,
    color: '#8b8fa3',
    display: 'flex',
    alignItems: 'center',
    gap: 6,
  },
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
