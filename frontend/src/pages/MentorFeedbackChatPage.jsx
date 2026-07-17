import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { askCommittee, getProject } from '../api/projectApi'
import { getDocuments } from '../api/documentApi'
import { docTypeLabel } from '../utils/docType'
import { formatFileSize } from '../utils/file'
import { personaColor, personaInitial, buildTranscript } from '../components/meeting/meetingTheme'
import CommitteeVideoStage from '../components/meeting/CommitteeVideoStage'
import StepSidebar from '../components/wizard/StepSidebar'

// 가은/Claude(2026-07-17): STEP7 "대화형 피드백" 화면 — 목업(ai_review_board_web.jsx)의
// 채팅형 Q&A UI를 실제로 구현. 이전엔 "대화형 피드백 진행 파트로 넘어가면 적용할 것"이라고
// 미뤄뒀던 부분(사용자 확정). 채팅 상단은 방금 끝난 회의 결과(reviewer_results +
// chair_summary)를 MeetingChat/MeetingSimulationPage와 같은 buildTranscript()로 그대로
// 재사용해 "위원들이 이미 한 말"로 보여주고, 그 아래 입력창으로 후속 질문을 하면
// POST /projects/:id/ask를 부른다. 어느 위원에게 물어볼지 사용자가 고르지 않아도, 서버가
// 질문 내용을 보고 관련 위원 1~3명(또는 위원장)을 자동으로 골라 답하므로(백엔드
// _build_routing_prompt) 응답이 배열(data.answers)로 온다 — 그대로 순서대로 버블 여러 개로
// 렌더링한다. 새 채점/저장은 없다. 대화 기록은 서버에 저장하지 않는 stateless 호출이라
// history를 매번 그대로 다시 보낸다.
//
// 가은/Claude(2026-07-17): 별도 페이지였던 영상 시뮬레이션(/simulation,
// MeetingSimulationPage — 이번에 삭제)의 CommitteeVideoStage(재인님 파일, 안 건드림)를
// 사용자 요청으로 이 화면 상단, 대화창 위로 옮겨왔다. media_script가 비어있으면(아직
// 영상 대본이 없는 회의) 영상 대신 안내 문구만 보여준다.
const SUGGESTED_QUESTIONS = [
  '가장 시급하게 고쳐야 할 부분은 무엇인가요?',
  '차별점을 어떤 방식으로 강화하면 좋을까요?',
  '실현 가능성을 높이려면 어떻게 보완해야 할까요?',
]

function Avatar({ name, personaId }) {
  const color = personaColor(personaId)
  return (
    <div style={{ ...styles.avatar, background: `${color}22`, color, border: `1.5px solid ${color}55` }}>
      {personaInitial(name)}
    </div>
  )
}

// 가은/Claude(2026-07-17): "/ask 답변이 몇십 초 기다렸다가 문단 전체가 한번에 뜨니까
// 너무 오래 걸리는 것처럼 느껴진다" — 실제 대기시간(라우팅+병렬 LLM 호출)을 줄이는 건
// 이미 했으니(asyncio.gather), 여기선 응답이 도착한 뒤 한 번에 뜨지 않고 타이핑치듯
// 글자가 점점 드러나게 해서 체감을 개선한다. 진짜 토큰 스트리밍(SSE)이 아니라 이미 다
// 받은 텍스트를 클라이언트에서만 애니메이션하는 것 — 답변 길이와 무관하게 총 애니메이션
// 시간이 비슷하도록 한 틱에 여러 글자씩 드러낸다. 마운트 시 한 번만 실행되면 되므로(같은
// 메시지가 리렌더된다고 다시 타이핑되지 않아야 함) key가 고정된 각 ChatBubble 인스턴스
// 안에서만 상태를 갖는다.
const TYPING_TICK_MS = 20
const TYPING_TARGET_MS = 900

function TypingText({ text, onTick }) {
  const [shown, setShown] = useState('')

  useEffect(() => {
    if (!text) {
      setShown('')
      return undefined
    }
    const totalTicks = Math.max(1, Math.round(TYPING_TARGET_MS / TYPING_TICK_MS))
    const chunkSize = Math.max(1, Math.ceil(text.length / totalTicks))
    let revealed = 0
    setShown('')
    const timer = setInterval(() => {
      revealed += chunkSize
      setShown(text.slice(0, revealed))
      onTick?.()
      if (revealed >= text.length) clearInterval(timer)
    }, TYPING_TICK_MS)
    return () => clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text])

  return shown
}

function ChatBubble({ speakerName, role, text, personaId, isUser, animate, onTick }) {
  const color = isUser ? '#7c4dff' : personaColor(personaId)
  return (
    <div style={{ ...styles.bubbleRow, ...(isUser ? styles.bubbleRowUser : {}) }}>
      {!isUser && <Avatar name={speakerName} personaId={personaId} />}
      <div style={{ ...styles.bubbleBody, ...(isUser ? styles.bubbleBodyUser : {}) }}>
        {!isUser && (
          <div style={styles.bubbleHeader}>
            <span style={{ ...styles.speakerName, color }}>{speakerName}</span>
            {role && role !== speakerName && <span style={styles.speakerRole}>{role}</span>}
          </div>
        )}
        <div
          style={{
            ...styles.bubble,
            ...(isUser ? styles.bubbleUser : { borderColor: `${color}33` }),
          }}
        >
          {animate ? <TypingText text={text} onTick={onTick} /> : text}
        </div>
      </div>
    </div>
  )
}

export default function MentorFeedbackChatPage() {
  const { projectId } = useParams()
  const navigate = useNavigate()
  const [result, setResult] = useState(null)
  const [project, setProject] = useState(null)
  const [targetDoc, setTargetDoc] = useState(null)
  const [messages, setMessages] = useState([])
  const [inputValue, setInputValue] = useState('')
  const [asking, setAsking] = useState(false)
  const [error, setError] = useState('')
  const historyRef = useRef([]) // [{question, answer}, ...] — /ask 호출마다 그대로 재전송
  const bottomRef = useRef(null)

  useEffect(() => {
    const cached = sessionStorage.getItem(`analysis:${projectId}`)
    if (cached) {
      const parsed = JSON.parse(cached)
      setResult(parsed)
      setMessages(buildTranscript(parsed).map((line) => ({ ...line, isUser: false })))
    }
    getProject(projectId).then(setProject).catch(() => {})
    getDocuments(projectId)
      .then((docs) => setTargetDoc(docs.find((d) => d.document_role !== 'criteria') || docs[0] || null))
      .catch(() => {})
  }, [projectId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, asking])

  async function handleAsk(questionText) {
    const question = (questionText ?? inputValue).trim()
    if (!question || asking) return
    setInputValue('')
    setError('')
    setMessages((prev) => [...prev, { isUser: true, text: question }])
    setAsking(true)
    try {
      const data = await askCommittee(projectId, question, historyRef.current)
      const answers = data.answers || []
      // 여러 위원이 한 질문에 같이 답할 수 있어서(_build_routing_prompt), 다음 요청에
      // 넘길 history는 화자별 답변을 한데 묶어 하나의 answer 문자열로 만든다.
      const combinedAnswer = answers.map((a) => `${a.display_name}: ${a.answer}`).join('\n')
      historyRef.current = [...historyRef.current, { question, answer: combinedAnswer }]
      setMessages((prev) => [
        ...prev,
        ...answers.map((a) => ({
          isUser: false,
          personaId: a.persona_id,
          speakerName: a.display_name,
          text: a.answer,
          animate: true,
        })),
      ])
    } catch (err) {
      setError(err.message)
    } finally {
      setAsking(false)
    }
  }

  if (!result) {
    return (
      <div style={styles.page}>
        <StepSidebar projectId={projectId} activeIndex={5} />
        <main style={styles.main}>
          <p style={styles.emptyText}>
            이 프로젝트의 분석 결과를 찾을 수 없습니다. 먼저 피드백 진행 단계를 완료해주세요.
          </p>
          <button style={styles.backButton} onClick={() => navigate(`/projects/${projectId}/analysis`)}>
            ← 공모전 분석으로
          </button>
        </main>
      </div>
    )
  }

  return (
    <div style={styles.page}>
      <StepSidebar projectId={projectId} activeIndex={5} />

      <main style={styles.main}>
        <div style={styles.stepLabel}>STEP 6 / 7</div>
        <h1 style={styles.title}>대화형 피드백</h1>

        <div style={styles.videoBox}>
          {Array.isArray(result.media_script) && result.media_script.length > 0 ? (
            <CommitteeVideoStage mediaLines={result.media_script} />
          ) : (
            <p style={styles.videoNotice}>
              이 회의는 아직 영상 대본(media_script)이 생성되지 않았습니다 — 위원 발언 없이
              대기 화면만 표시됩니다.
            </p>
          )}
        </div>

        <div style={styles.chatArea}>
          {messages.map((m, i) => (
            <ChatBubble
              key={i}
              {...m}
              onTick={() => bottomRef.current?.scrollIntoView({ block: 'end' })}
            />
          ))}
          {asking && (
            <div style={styles.bubbleRow}>
              {/* 가은/Claude(2026-07-17): 어느 위원이 답할지는 서버 라우팅(_build_routing_prompt)
                  결과가 와야 알 수 있어서, 로딩 중엔 특정 위원 아바타 대신 중립 아이콘을 쓴다. */}
              <div style={styles.loadingAvatar}>⋯</div>
              <div style={styles.bubbleBody}>
                <div style={styles.bubble}>위원들이 답변을 준비하고 있어요...</div>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {historyRef.current.length === 0 && (
          <div style={styles.suggestionRow}>
            {SUGGESTED_QUESTIONS.map((q) => (
              <button key={q} style={styles.suggestionChip} onClick={() => handleAsk(q)} disabled={asking}>
                {q}
              </button>
            ))}
          </div>
        )}

        {error && <p style={styles.error}>{error}</p>}

        <form
          style={styles.inputRow}
          onSubmit={(e) => {
            e.preventDefault()
            handleAsk()
          }}
        >
          <input
            style={styles.input}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder="질문을 입력하세요"
            disabled={asking}
          />
          <button type="submit" style={styles.sendButton} disabled={asking || !inputValue.trim()}>
            ➤
          </button>
        </form>
        <p style={styles.inputHint}>추가 질문 가능 · 연속 대화 가능</p>
      </main>

      <aside style={styles.rightPanel}>
        <div style={styles.assistantBubbleRow}>
          <div style={styles.assistantIcon}>✨</div>
          <div style={styles.assistantBubble}>
            받은 피드백에 이어서 궁금한 점을 자유롭게 질문해보세요. 아래에서 기획서 원문도 바로
            확인할 수 있어요.
          </div>
        </div>

        <div style={styles.sectionLabel}>기획서 원문 대조</div>
        <div style={styles.docPreview}>
          {targetDoc ? (
            <>
              <div style={styles.docIcon}>📄</div>
              <div style={styles.docName}>{targetDoc.original_filename}</div>
              <div style={styles.docMeta}>
                {formatFileSize(targetDoc.file_size)} · 원문 미리보기는 준비 중이에요
              </div>
            </>
          ) : (
            <div style={styles.docMeta}>문서 정보를 불러오는 중...</div>
          )}
        </div>

        <button style={styles.resultButton} onClick={() => navigate(`/projects/${projectId}`)}>
          결과 정리 보기
        </button>

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
  main: { padding: '24px 32px', display: 'flex', flexDirection: 'column', minWidth: 0 },
  stepLabel: { fontSize: 12, fontWeight: 700, color: ACCENT, letterSpacing: 0.5 },
  title: { fontSize: 22, fontWeight: 700, margin: '4px 0 20px' },
  videoBox: { marginBottom: 20 },
  videoNotice: {
    fontSize: 12.5,
    color: '#9a6400',
    background: '#fdf1d6',
    padding: '10px 14px',
    borderRadius: 8,
    textAlign: 'center',
  },
  emptyText: { maxWidth: 420, margin: '80px auto 20px', textAlign: 'center', color: '#8b8fa3', fontSize: 14 },
  backButton: {
    display: 'block',
    margin: '0 auto',
    border: 'none',
    background: 'transparent',
    color: ACCENT,
    fontWeight: 600,
    cursor: 'pointer',
    fontSize: 13,
  },
  chatArea: { flex: 1, display: 'flex', flexDirection: 'column', gap: 18, overflowY: 'auto', paddingBottom: 12 },
  bubbleRow: { display: 'flex', gap: 12, alignItems: 'flex-start' },
  bubbleRowUser: { flexDirection: 'row-reverse' },
  avatar: {
    flexShrink: 0,
    width: 36,
    height: 36,
    borderRadius: '50%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontWeight: 700,
    fontSize: 14,
  },
  loadingAvatar: {
    flexShrink: 0,
    width: 36,
    height: 36,
    borderRadius: '50%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontWeight: 700,
    fontSize: 14,
    background: `${ACCENT}22`,
    color: ACCENT,
    border: `1.5px solid ${ACCENT}55`,
  },
  bubbleBody: { flex: 1, minWidth: 0, maxWidth: '78%' },
  bubbleBodyUser: { display: 'flex', flexDirection: 'column', alignItems: 'flex-end', marginLeft: 'auto' },
  bubbleHeader: { display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 4 },
  speakerName: { fontWeight: 700, fontSize: 14 },
  speakerRole: { fontSize: 12, color: '#7994ac' },
  bubble: {
    background: '#fff',
    border: '1px solid #ece9f7',
    borderRadius: '4px 14px 14px 14px',
    padding: '10px 14px',
    fontSize: 14,
    lineHeight: 1.55,
  },
  bubbleUser: {
    background: ACCENT,
    color: '#fff',
    border: 'none',
    borderRadius: '14px 4px 14px 14px',
  },
  suggestionRow: { display: 'flex', flexWrap: 'wrap', gap: 8, margin: '14px 0' },
  suggestionChip: {
    fontSize: 12.5,
    fontWeight: 600,
    color: ACCENT,
    background: `${ACCENT}12`,
    border: `1px solid ${ACCENT}33`,
    borderRadius: 999,
    padding: '8px 14px',
    cursor: 'pointer',
  },
  error: { color: '#d64545', fontSize: 13, marginBottom: 8 },
  inputRow: { display: 'flex', gap: 8, marginTop: 8 },
  input: {
    flex: 1,
    padding: '12px 16px',
    borderRadius: 999,
    border: '1px solid #ded9f2',
    fontSize: 14,
    outline: 'none',
  },
  sendButton: {
    width: 44,
    height: 44,
    borderRadius: '50%',
    border: 'none',
    background: ACCENT,
    color: '#fff',
    fontSize: 16,
    cursor: 'pointer',
    flexShrink: 0,
  },
  inputHint: { fontSize: 11.5, color: '#a1a5b8', marginTop: 6 },
  rightPanel: { borderLeft: '1px solid #ece9f7', padding: '20px 16px', overflowY: 'auto' },
  assistantBubbleRow: { display: 'flex', gap: 10, marginBottom: 22 },
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
  sectionLabel: { fontSize: 12, fontWeight: 700, color: '#8b8fa3', marginBottom: 10 },
  docPreview: {
    background: '#fbfbfe',
    border: '1px dashed #d8d5ec',
    borderRadius: 12,
    padding: 20,
    textAlign: 'center',
    marginBottom: 16,
  },
  docIcon: { fontSize: 26, marginBottom: 8 },
  docName: { fontSize: 13, fontWeight: 600, color: '#4b4f63', wordBreak: 'break-all' },
  docMeta: { fontSize: 11.5, color: '#a1a5b8', marginTop: 4 },
  resultButton: {
    display: 'block',
    width: '100%',
    padding: '12px 0',
    borderRadius: 12,
    border: 'none',
    background: ACCENT,
    color: '#fff',
    fontSize: 13.5,
    fontWeight: 700,
    cursor: 'pointer',
    marginBottom: 22,
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
