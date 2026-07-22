import { useEffect, useRef, useState } from 'react'
import { AlertCircle, ChevronDown, ChevronUp, RefreshCw, Send, Sparkles } from 'lucide-react'
import {
  finalizeIdeationConversation,
  getIdeationConversation,
  replyIdeationConversation,
  replyIdeationConversationStream,
  startIdeationConversation,
} from '../../api/ideationConversationApi'
import { getAnnouncementAnalysis } from '../../api/documentApi'
import {
  EXPERT_RECOMMEND_MESSAGE,
  FEASIBILITY_LABEL,
  REGENERATE_MESSAGE,
  buildCompetitionDocumentText,
  candidateSelectMessage,
  classifyIdeationConvError,
  competitionNameFrom,
  nextActionGuideFor,
  resolveUseRag,
  speakerMetaFor,
  statusLabelFor,
} from './ideationConversationHelpers'
import {
  advanceDisplay,
  applyStreamEvent,
  charsPerTickFor,
  createEmptyStreamState,
  dedupeMessagesById,
  isFullyDisplayed,
  pendingCharCount,
} from './ideationStreamReducer'

// 작성자: 용준/Claude(2026-07-21)
// 목적: /board "작성 전 → 주제 발굴" 흐름의 실제 대화형 아이디어 회의 화면.
//       기존 ReviewBoardPrototype.jsx 안의 더미 IdeationScreen/IdeationResultScreen
//       (고정 문자열·setTimeout·고정 후보/결과)을 대체한다. 페르소나 로직·질문 생성·
//       답변 충분성 판정·후보 결합 해석은 전부 기존 백엔드(ai/meeting 그래프 +
//       ideation_conv_*.txt 프롬프트)가 그대로 수행하고, 이 화면은 그 결과(messages/
//       idea_candidates/phase/...)를 /board의 웜 화이트 디자인(card glass, badge,
//       btn-primary/ghost — ReviewBoardPrototype.jsx의 Shell이 정의)으로 그릴 뿐이다.
//       API 연동 방식은 IdeationConversationPreviewPage.jsx(개발용 프리뷰)를 참고했지만
//       그 화면의 디자인을 옮겨오지는 않았다.
//
//       session_id/최신 회의 결과(ideationConv)는 이 컴포넌트가 아니라 부모
//       (ReviewBoardPrototype)의 state로 관리된다 — "이전 단계로 갔다 돌아와도 회의 상태
//       유지"를 만족시키려면, 이 화면이 언마운트됐다 다시 마운트돼도(사이드바로 다른
//       단계를 갔다 오는 경우) 이미 진행 중이던 세션을 잃지 않아야 하기 때문이다. 그래서
//       "start API를 한 번만 호출"하는 가드도 두 겹이다: ① 부모가 이미 ideationConv를
//       들고 있으면(=한 번이라도 시작 성공) 이 컴포넌트는 절대 다시 start를 호출하지
//       않는다(항상 최우선으로 검사), ② 아직 없다면 이번 마운트에서 한 번만 시도하도록
//       useRef 가드를 둔다(React StrictMode의 개발 모드 이중 effect 호출에도 안전 —
//       ref는 같은 컴포넌트 인스턴스의 마운트/언마운트/재마운트 사이에 유지된다).

const REPLYABLE_PHASES = new Set([
  'awaiting_candidate_selection',
  'awaiting_planning_answer',
  'awaiting_developer_answer',
  'awaiting_user_decision',
])

function ideationSessionStorageKey(projectId) {
  return projectId ? `ideation-conv-session:${projectId}` : null
}

// 커서 깜빡임 애니메이션 — Shell(ReviewBoardPrototype.jsx)의 전역 <style>을 건드리지 않고
// 이 컴포넌트 전용으로 한 번만 주입한다(기존 코드베이스가 Shell에서 이미 쓰는 "JSX 안에
// <style> 태그를 직접 렌더링"하는 패턴 그대로).
function StreamingCursorStyle() {
  return (
    <style>{`
      @keyframes rb-ideation-cursor-blink { 0%, 49% { opacity: 1; } 50%, 100% { opacity: 0; } }
      .rb-ideation-cursor { display: inline-block; width: 2px; margin-left: 1px; background: currentColor; animation: rb-ideation-cursor-blink 1s step-start infinite; }
    `}</style>
  )
}

function MessageBubble({ message, streaming = false }) {
  const meta = speakerMetaFor(message)
  const isRight = meta.align === 'right'
  // 스트리밍 중인 말풍선은 displayedContent(타이핑 큐가 드러낸 만큼)만 보여준다 —
  // content(서버에서 실제로 받은 전체 텍스트)를 그대로 쓰면 델타가 도착하는 순간
  // 문장이 통째로 튀어나와 타이핑 효과가 사라진다. canonical(완료된) 메시지는
  // displayedContent 필드가 없으므로 content를 그대로 쓴다.
  const text = streaming ? message.displayedContent ?? '' : message.content
  const hasContent = !!text?.trim()
  // done(message_end 수신)이 와도 displayedContent가 content를 따라잡기 전까지는
  // 커서를 유지한다 — "message_end가 와도 남은 글자 큐를 끝까지 표시"(요청 사항).
  const caughtUp = (message.displayedContent?.length ?? 0) >= (message.content?.length ?? 0)
  const showCursor = streaming && !caughtUp

  if (!hasContent && !streaming) {
    return (
      <div style={{ display: 'flex', justifyContent: isRight ? 'flex-end' : 'flex-start', marginBottom: 10 }}>
        <div style={{ fontSize: 12.5, color: 'var(--coral)' }}>
          <AlertCircle size={12} style={{ verticalAlign: -1, marginRight: 4 }} />
          {meta.label}의 응답을 만드는 중 오류가 발생했습니다.
        </div>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', justifyContent: isRight ? 'flex-end' : 'flex-start', marginBottom: 10 }}>
      <div style={{ maxWidth: '82%' }}>
        {meta.badgeClass && (
          <div className={`badge ${meta.badgeClass} mono`} style={{ marginBottom: 4 }}>
            {meta.label}
          </div>
        )}
        <div
          style={{
            background: isRight ? 'var(--purple-dim)' : 'var(--bg-1)',
            border: '1px solid var(--glass-border)',
            borderRadius: 12,
            padding: '10px 14px',
            fontSize: 13.5,
            lineHeight: 1.6,
            whiteSpace: 'pre-wrap',
          }}
        >
          {text}
          {showCursor && <span className="rb-ideation-cursor">▍</span>}
        </div>
      </div>
    </div>
  )
}

function CandidateCard({ candidate, index, onSelect, disabled }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div className="card glass" style={{ marginBottom: 10, padding: 14 }}>
      <div style={{ fontSize: 11.5, color: 'var(--text-2)', marginBottom: 2 }}>후보 {index + 1}</div>
      <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 6 }}>{candidate.title}</div>
      <div style={{ fontSize: 12.5, color: 'var(--text-1)', lineHeight: 1.6, marginBottom: 4 }}>
        <strong style={{ color: 'var(--text-2)', fontWeight: 600 }}>해결할 문제 · </strong>
        {candidate.problem}
      </div>
      <div style={{ fontSize: 12.5, color: 'var(--text-1)', lineHeight: 1.6, marginBottom: 4 }}>
        <strong style={{ color: 'var(--text-2)', fontWeight: 600 }}>목표 사용자 · </strong>
        {candidate.target_user}
      </div>

      <button
        className="btn-ghost"
        style={{ padding: '4px 10px', fontSize: 11.5, marginTop: 4, marginBottom: expanded ? 8 : 0, display: 'flex', alignItems: 'center', gap: 4 }}
        onClick={() => setExpanded((v) => !v)}
      >
        {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        {expanded ? '간단히 보기' : '상세 보기'}
      </button>

      {expanded && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 6 }}>
          <div style={{ fontSize: 12.5, color: 'var(--text-1)', lineHeight: 1.6 }}>
            <strong style={{ color: 'var(--text-2)', fontWeight: 600 }}>핵심 가치 · </strong>
            {candidate.core_value}
          </div>
          {candidate.main_features?.length > 0 && (
            <div style={{ fontSize: 12.5, color: 'var(--text-1)' }}>
              <strong style={{ color: 'var(--text-2)', fontWeight: 600 }}>주요 기능</strong>
              <ul style={{ margin: '4px 0 0', paddingLeft: 16, lineHeight: 1.7 }}>
                {candidate.main_features.map((f, i) => <li key={i}>{f}</li>)}
              </ul>
            </div>
          )}
          <div style={{ fontSize: 12.5, color: 'var(--text-1)', lineHeight: 1.6 }}>
            <strong style={{ color: 'var(--text-2)', fontWeight: 600 }}>공모전 적합성 · </strong>
            {candidate.contest_fit || '확인되지 않음'}
          </div>
          {candidate.risks?.length > 0 && (
            <div style={{ fontSize: 12.5, color: 'var(--text-1)' }}>
              <strong style={{ color: 'var(--text-2)', fontWeight: 600 }}>주요 위험</strong>
              <ul style={{ margin: '4px 0 0', paddingLeft: 16, lineHeight: 1.7 }}>
                {candidate.risks.map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}

      <div style={{ fontSize: 11.5, color: 'var(--text-2)', marginBottom: 10 }}>
        실현 가능성 {FEASIBILITY_LABEL[candidate.feasibility] || '미상'}
      </div>

      <button className="btn-primary" style={{ width: '100%', padding: '8px 0', fontSize: 12.5 }} disabled={disabled} onClick={() => onSelect(index)}>
        이 후보 선택
      </button>
    </div>
  )
}

function MergeAnalysisPanel({ mergeAnalysis, sourceCandidates, userSelectionMessage }) {
  if (!mergeAnalysis) return null
  return (
    <div className="card glass" style={{ marginBottom: 12, padding: 14 }}>
      <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>결합 분석</div>
      {userSelectionMessage && (
        <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 8 }}>
          원문 요청 · “{userSelectionMessage}”
        </div>
      )}
      {sourceCandidates?.length > 0 && (
        <div style={{ fontSize: 12.5, color: 'var(--text-1)', marginBottom: 8 }}>
          <strong style={{ color: 'var(--text-2)', fontWeight: 600 }}>원본 후보 · </strong>
          {sourceCandidates.map((c) => c.title).join(' · ')}
        </div>
      )}
      <div style={{ fontSize: 12.5, color: 'var(--text-1)', lineHeight: 1.6, marginBottom: 4 }}>
        <strong style={{ color: 'var(--text-2)', fontWeight: 600 }}>공통 문제 · </strong>{mergeAnalysis.common_problem}
      </div>
      <div style={{ fontSize: 12.5, color: 'var(--text-1)', lineHeight: 1.6, marginBottom: 4 }}>
        <strong style={{ color: 'var(--text-2)', fontWeight: 600 }}>공통 가치 · </strong>{mergeAnalysis.common_value}
      </div>
      <div style={{ fontSize: 12.5, color: 'var(--text-1)', lineHeight: 1.6, marginBottom: 4 }}>
        <strong style={{ color: 'var(--text-2)', fontWeight: 600 }}>결합 적합도 · </strong>
        {FEASIBILITY_LABEL[mergeAnalysis.fit] || mergeAnalysis.fit || '미상'}
      </div>
      {mergeAnalysis.primary_features?.length > 0 && (
        <div style={{ fontSize: 12.5, color: 'var(--text-1)', marginBottom: 4 }}>
          <strong style={{ color: 'var(--text-2)', fontWeight: 600 }}>주 기능</strong>
          <ul style={{ margin: '4px 0 0', paddingLeft: 16, lineHeight: 1.6 }}>
            {mergeAnalysis.primary_features.map((f, i) => <li key={i}>{f}</li>)}
          </ul>
        </div>
      )}
      {mergeAnalysis.secondary_features?.length > 0 && (
        <div style={{ fontSize: 12.5, color: 'var(--text-1)', marginBottom: 4 }}>
          <strong style={{ color: 'var(--text-2)', fontWeight: 600 }}>보조 기능</strong>
          <ul style={{ margin: '4px 0 0', paddingLeft: 16, lineHeight: 1.6 }}>
            {mergeAnalysis.secondary_features.map((f, i) => <li key={i}>{f}</li>)}
          </ul>
        </div>
      )}
      {mergeAnalysis.conflicts?.length > 0 && (
        <div style={{ fontSize: 12.5, color: 'var(--text-1)', marginBottom: 4 }}>
          <strong style={{ color: 'var(--text-2)', fontWeight: 600 }}>충돌 지점</strong>
          <ul style={{ margin: '4px 0 0', paddingLeft: 16, lineHeight: 1.6 }}>
            {mergeAnalysis.conflicts.map((c, i) => <li key={i}>{c}</li>)}
          </ul>
        </div>
      )}
      {mergeAnalysis.open_questions?.length > 0 && (
        <div style={{ fontSize: 12.5, color: 'var(--text-1)' }}>
          <strong style={{ color: 'var(--text-2)', fontWeight: 600 }}>미확정 사항</strong>
          <ul style={{ margin: '4px 0 0', paddingLeft: 16, lineHeight: 1.6 }}>
            {mergeAnalysis.open_questions.map((q, i) => <li key={i}>{q}</li>)}
          </ul>
        </div>
      )}
    </div>
  )
}

function ErrorBanner({ error, onRetry }) {
  if (!error) return null
  return (
    <div
      className="card glass"
      style={{ borderColor: 'var(--coral-dim)', marginBottom: 14, display: 'flex', alignItems: 'flex-start', gap: 10, padding: 14 }}
    >
      <AlertCircle size={16} color="var(--coral)" style={{ marginTop: 1, flexShrink: 0 }} />
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13, color: 'var(--text-0)', lineHeight: 1.6 }}>{error.message}</div>
        {onRetry && (
          <button className="btn-ghost" style={{ marginTop: 10, padding: '6px 12px', fontSize: 12, display: 'flex', alignItems: 'center', gap: 6 }} onClick={onRetry}>
            <RefreshCw size={12} /> 다시 시도
          </button>
        )}
      </div>
    </div>
  )
}

// 요청: "스트리밍이 비활성화되거나 fallback됐다면 화면 또는 콘솔에 그 이유가 드러나게
// 해주세요. 조용히 기존 /reply로 fallback해서는 안 됩니다." — /reply/stream이 404(플래그
// 꺼짐)로 응답해 동기식 /reply로 전환할 때 이 배너를 띄운다(handleSend가 console.warn도
// 함께 남긴다). ErrorBanner와 달리 재시도 버튼이 없다 — 오류가 아니라 "이번 세션은 계속
// 이 방식으로 동작한다"는 지속 안내이기 때문이다.
function StreamFallbackNotice({ message }) {
  if (!message) return null
  return (
    <div
      className="card glass"
      style={{ borderColor: 'var(--amber-dim, var(--glass-border))', marginBottom: 14, display: 'flex', alignItems: 'flex-start', gap: 10, padding: 12 }}
    >
      <AlertCircle size={14} color="var(--amber, var(--coral))" style={{ marginTop: 1, flexShrink: 0 }} />
      <div style={{ fontSize: 12.5, color: 'var(--text-1)', lineHeight: 1.6 }}>{message}</div>
    </div>
  )
}

export function IdeationScreen({
  projectId,
  criteriaDocuments,
  ideationConv,
  setIdeationConv,
  onFinalized,
  onBack,
  saving = false,
  saveError = '',
}) {
  const [starting, setStarting] = useState(!ideationConv)
  const [sending, setSending] = useState(false)
  const [finalizing, setFinalizing] = useState(false)
  const [error, setError] = useState(null)
  const [draft, setDraft] = useState('')
  // 용준/Claude(2026-07-21, 요청: 실시간 스트리밍) — 지금 스트리밍 중인(아직 canonical이
  // 아닌) 메시지만 별도로 들고 있는다. 서버가 최종 state 이벤트를 보내면 이 값은 통째로
  // createEmptyStreamState()로 비우고 ideationConv(canonical)만 그린다 — 그래서 스트리밍
  // 미리보기와 canonical 메시지가 동시에 화면에 남아 중복되는 경우가 구조적으로 없다.
  const [streamState, setStreamState] = useState(() => createEmptyStreamState())
  // 요청: "스트리밍이 비활성화되거나 fallback됐다면 화면 또는 콘솔에 그 이유가 드러나게
  // 해주세요" — 동기식 /reply로 전환했을 때 사용자에게 보여줄 지속 안내 문구.
  const [streamFallbackNotice, setStreamFallbackNotice] = useState(null)

  const startedRef = useRef(false)
  const chatEndRef = useRef(null)
  const streamAbortRef = useRef(null)
  // 스트리밍 엔드포인트가 비활성화(404)로 확인되면 이 세션 동안은 다시 시도하지 않고
  // 동기식 API로만 보낸다(요청: "플래그가 꺼져 있으면 기존 비스트리밍 API로 돌아갈 수
  // 있도록") — 단, 전환 시점에는 console.warn + streamFallbackNotice로 반드시 알린다
  // (요청: "조용히 기존 /reply로 fallback해서는 안 됩니다").
  const streamingSupportedRef = useRef(true)
  // 네트워크로부터 최종 'state'(또는 'error') 이벤트를 이미 받았지만, 아직 화면 타이핑이
  // 그 텍스트를 다 따라잡지 못해 canonical로 교체를 미루고 있는 상태를 담는다. ref인
  // 이유: 이 값 자체는 화면에 아무것도 그리지 않으므로 리렌더를 유발할 필요가 없고,
  // 아래 rAF 루프가 매 프레임 읽기만 하면 된다.
  const pendingFinalRef = useRef(null)
  // 방어 코드(요청: "중복 버그" 진단) — 실제 원인은 서버 쪽에서 재현하지 못했다(계획 문서
  // 1번 참고). 남은 유력 용의점은 이 rAF 루프 effect가 (StrictMode 이중 호출 등으로) 두 번
  // 동시에 도는 경우다 — 이 ref로 같은 컴포넌트 인스턴스에서 루프가 항상 하나만 돌게 막는다.
  const rafLoopActiveRef = useRef(false)

  useEffect(() => {
    return () => {
      // 요청: "컴포넌트 unmount 시 요청 취소".
      streamAbortRef.current?.abort()
      pendingFinalRef.current = null
    }
  }, [])

  // 실제 LLM 델타가 도착하는 즉시 content(수신 텍스트)는 이미 갱신돼 있다 — 이 루프는
  // "화면에 보여주는 속도"만 조절한다(요청: "requestAnimationFrame 또는 짧은 타이머로
  // 큐에서 1~2글자씩 displayedText에 추가"). sending이 true인 동안 계속 돌며, 네트워크가
  // 끝나 pendingFinalRef가 채워져도 화면 타이핑이 content를 다 따라잡을 때까지는 계속
  // 돈다 — 다 따라잡은 순간에만 canonical state로 교체한다(요청: "최종 state가 먼저
  // 도착해도 임시 스트림 메시지를 즉시 삭제하지 않음").
  useEffect(() => {
    if (!sending) return
    if (rafLoopActiveRef.current) return // 이미 다른 루프가 돌고 있으면 두 번째 루프를 시작하지 않는다.
    rafLoopActiveRef.current = true
    let rafId
    let cancelled = false

    function finalizeStream(finalState, errorEvent) {
      if (errorEvent) {
        setError(classifyIdeationConvError(new Error(errorEvent.message)))
      } else if (finalState) {
        setIdeationConv(finalState)
        setDraft('')
      } else {
        // state/error 이벤트를 하나도 못 받은 채 스트림이 끝났다(연결이 조기 종료된 경우
        // 등) — 회의 화면은 유지하되 무엇이 잘못됐는지 알린다.
        setError(classifyIdeationConvError(new Error('스트리밍 응답이 완료되지 않았습니다.')))
      }
      setSending(false)
    }

    function tick() {
      if (cancelled) return
      setStreamState((prev) => {
        const pending = pendingCharCount(prev)
        const next = pending > 0 ? advanceDisplay(prev, charsPerTickFor(pending)) : prev
        if (pendingFinalRef.current && isFullyDisplayed(next)) {
          const { finalState, errorEvent } = pendingFinalRef.current
          pendingFinalRef.current = null
          // setState 업데이터 함수 안에서 다른 컴포넌트 상태를 직접 바꾸면 안 되므로
          // (React 경고 대상), 렌더 커밋 이후로 미룬다.
          queueMicrotask(() => finalizeStream(finalState, errorEvent))
          return createEmptyStreamState()
        }
        return next
      })
      rafId = requestAnimationFrame(tick)
    }
    rafId = requestAnimationFrame(tick)

    return () => {
      cancelled = true
      if (rafId) cancelAnimationFrame(rafId)
      rafLoopActiveRef.current = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sending])

  async function runStart() {
    setStarting(true)
    setError(null)
    try {
      let analysis = { has_announcement: false }
      if (projectId) {
        analysis = await getAnnouncementAnalysis(projectId)
      }
      const data = await startIdeationConversation({
        competitionName: competitionNameFrom(analysis),
        competitionDocument: buildCompetitionDocumentText(analysis),
        userIdea: '', // discovery 모드로 시작해야 하므로 반드시 빈 문자열로 보낸다.
        maxRounds: 3,
        useRag: resolveUseRag(projectId, criteriaDocuments),
        projectId,
      })
      setIdeationConv(data)
      const key = ideationSessionStorageKey(projectId)
      if (key) sessionStorage.setItem(key, data.session_id)
    } catch (err) {
      setError(classifyIdeationConvError(err))
    } finally {
      setStarting(false)
    }
  }

  // 부모(ReviewBoardPrototype)가 이미 진행 중인 회의 결과를 들고 있으면(다른 단계로
  // 갔다 돌아온 경우) 절대 다시 시작하지 않는다. 처음 진입할 때만, 그리고 이번 마운트에서
  // 딱 한 번만 시도한다.
  useEffect(() => {
    if (ideationConv || startedRef.current) return
    startedRef.current = true

    const key = ideationSessionStorageKey(projectId)
    const savedSessionId = key ? sessionStorage.getItem(key) : null
    if (!savedSessionId) {
      runStart()
      return
    }
    setStarting(true)
    getIdeationConversation(savedSessionId)
      .then((data) => setIdeationConv(data))
      .catch(() => {
        if (key) sessionStorage.removeItem(key)
        return runStart()
      })
      .finally(() => setStarting(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
    // 화면에 실제로 드러난 글자 수(displayedContent)가 늘어날 때(타이핑 진행)마다도
    // 스크롤해야 하므로, 배열 참조 자체가 아니라 지금까지 누적된 총 글자 수를 의존값으로
    // 쓴다(요청: "delta가 들어올 때 자동 스크롤" — content가 아니라 실제 화면 표시 기준).
  }, [ideationConv?.messages?.length, streamState.messages.reduce((n, m) => n + (m.displayedContent?.length || 0), 0)])

  const phase = ideationConv?.phase
  const busy = starting || sending || finalizing || saving
  // awaiting_user_decision도 입력을 막지 않는다("더 이야기하기") — 백엔드
  // apply_user_answer가 이 경우도 받아 두 전문가 보완 의견으로 이어간다.
  const canReplyOrContinue = !!ideationConv && REPLYABLE_PHASES.has(phase) && !busy
  const canFinalize = !!ideationConv && phase === 'awaiting_user_decision' && !busy
  const hasCandidates = (ideationConv?.idea_candidates?.length || 0) > 0
  const hasSelected = !!ideationConv?.selected_idea

  async function sendNonStreaming(text) {
    try {
      const data = await replyIdeationConversation(ideationConv.session_id, text)
      setIdeationConv(data)
      setDraft('')
    } catch (err) {
      setError(classifyIdeationConvError(err))
    }
  }

  // 용준/Claude(2026-07-21, 요청: 실시간 스트리밍) — 실제 OpenAI 토큰이 도착하는 즉시
  // content(streamState)가 갱신된다(완성된 응답을 받은 뒤 재생하는 가짜 타이핑 아님).
  // 화면에 얼마나 드러낼지(displayedContent)는 위 rAF 루프가 별도로 조절한다. 이 함수는
  // 네트워크가 끝나도 곧바로 canonical로 교체하지 않는다 — 최종 state/error를
  // pendingFinalRef에 넘겨두기만 하고, 실제 교체·setSending(false)는 화면 타이핑이 다
  // 따라잡은 뒤 rAF 루프의 finalizeStream이 수행한다.
  async function handleSend(overrideText) {
    const text = (overrideText ?? draft).trim()
    if (!text || !ideationConv || !canReplyOrContinue) return
    setSending(true)
    setError(null)
    setStreamFallbackNotice(null)

    if (!streamingSupportedRef.current) {
      await sendNonStreaming(text)
      setSending(false)
      return
    }

    setStreamState(createEmptyStreamState())
    pendingFinalRef.current = null
    const controller = new AbortController()
    streamAbortRef.current = controller
    let finalState = null
    let streamErrorEvent = null
    try {
      await replyIdeationConversationStream(ideationConv.session_id, text, {
        signal: controller.signal,
        onEvent: (event) => {
          if (event.type === 'state') {
            finalState = event.state
          } else if (event.type === 'error') {
            streamErrorEvent = event
          } else {
            setStreamState((prev) => applyStreamEvent(prev, event))
          }
        },
      })
    } catch (err) {
      streamAbortRef.current = null
      setStreamState(createEmptyStreamState())
      pendingFinalRef.current = null
      if (err?.name === 'AbortError') {
        // 사용자가 화면을 벗어나 요청을 취소한 경우 — 오류로 취급하지 않는다.
        setSending(false)
        return
      }
      const classified = classifyIdeationConvError(err)
      if (classified.type === 'disabled') {
        // 스트리밍 자체가 꺼져 있다(/reply/stream 404) — 이번 세션은 이후 계속 동기식
        // API만 쓴다. 요청: "조용히 기존 /reply로 fallback해서는 안 됩니다" — 콘솔과
        // 화면 배너 양쪽에 이유를 남긴 뒤에만 전환한다.
        streamingSupportedRef.current = false
        console.warn(
          '[ideation-stream] POST /reply/stream 이 비활성화(404) 응답을 반환해 동기식 /reply로 전환합니다. ' +
            '백엔드 backend/.env의 ENABLE_IDEATION_STREAMING 값을 확인하세요.',
          err,
        )
        setStreamFallbackNotice(
          '실시간 스트리밍 응답이 비활성화되어 있어 일반 응답 방식으로 전환했습니다. (백엔드 ENABLE_IDEATION_STREAMING 설정을 확인하세요)',
        )
        await sendNonStreaming(text)
        setSending(false)
        return
      }
      setError(classified)
      setSending(false)
      return
    }

    streamAbortRef.current = null
    // 요청: "최종 state가 먼저 도착해도 임시 스트림 메시지를 즉시 삭제하지 않음" — 여기서는
    // canonical로 바꾸지 않고 rAF 루프가 화면 타이핑을 다 끝낸 뒤 처리하도록 넘겨둔다.
    pendingFinalRef.current = { finalState, errorEvent: streamErrorEvent }
  }

  async function handleFinalize() {
    if (!canFinalize) return
    setFinalizing(true)
    setError(null)
    try {
      const data = await finalizeIdeationConversation(ideationConv.session_id)
      setIdeationConv(data)
      if (data.phase === 'finalized') {
        await onFinalized(data)
      }
    } catch (err) {
      setError(classifyIdeationConvError(err))
    } finally {
      setFinalizing(false)
    }
  }

  function handleRestart() {
    const key = ideationSessionStorageKey(projectId)
    if (key) sessionStorage.removeItem(key)
    setIdeationConv(null)
    setError(null)
    startedRef.current = false
    runStart()
  }

  // 이미 확정까지 끝난 세션으로 이 화면에 돌아온 경우(사이드바 재진입) — 다시 채팅하지
  // 않고 바로 결과로 넘어갈 수 있게만 안내한다.
  if (ideationConv?.phase === 'finalized') {
    return (
      <div style={{ maxWidth: 860 }}>
        <div className="badge green mono" style={{ marginBottom: 10 }}>주제 확정 완료</div>
        <h2 style={{ fontSize: 20, fontWeight: 700, marginBottom: 16 }}>이미 이 회의로 주제를 확정했어요</h2>
        {saveError && <p style={{ color: 'var(--coral)', fontSize: 13, marginBottom: 12 }}>{saveError}</p>}
        <button
          className="btn-primary"
          style={{ display: 'flex', alignItems: 'center', gap: 8 }}
          onClick={() => onFinalized(ideationConv)}
          disabled={saving}
        >
          {saving ? '프로젝트 저장 중...' : saveError ? '프로젝트 저장 다시 시도' : '확정 결과 보기'}
        </button>
      </div>
    )
  }

  return (
    <div className="rb-grid-2" style={{ maxWidth: 900, display: 'grid', gridTemplateColumns: '1fr 320px', gap: 20 }}>
      <div>
        <div className="badge coral mono" style={{ marginBottom: 10 }}>주제 아이디어 회의</div>
        {onBack && (
          <button className="btn-ghost" style={{ marginBottom: 10, padding: '5px 10px', fontSize: 12 }} onClick={onBack} disabled={busy}>
            ← 이전
          </button>
        )}
        {ideationConv?.competition_name ? (
          <>
            <div style={{ fontSize: 12, color: 'var(--text-2)', fontFamily: 'var(--mono)', marginBottom: 4 }}>공모전 주제</div>
            <h2 style={{ fontSize: 20, fontWeight: 700, marginBottom: 4 }}>{ideationConv.competition_name}</h2>
            <div style={{ fontSize: 13, color: 'var(--text-2)', marginBottom: 10 }}>기획 위원 · 개발 위원과 함께 좁혀가는 중</div>
          </>
        ) : (
          <h2 style={{ fontSize: 20, fontWeight: 700, marginBottom: 10 }}>기획 위원 · 개발 위원과 함께 좁혀가는 중</h2>
        )}
        <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
          {ideationConv && (
            <span className="badge amber mono">
              {statusLabelFor({ phase, starting, sending, finalizing })}
            </span>
          )}
          {ideationConv && (
            <span className="badge purple mono">라운드 {ideationConv.round}/{ideationConv.max_rounds}</span>
          )}
        </div>

        <ErrorBanner error={error} onRetry={handleRestart} />
        <StreamFallbackNotice message={streamFallbackNotice} />
        <StreamingCursorStyle />

        <div className="card glass" style={{ minHeight: 360, maxHeight: 520, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4, padding: 16 }}>
          {starting && !ideationConv && (
            <p style={{ color: 'var(--text-2)', fontSize: 13 }}>공모전 분석을 바탕으로 아이디어 후보를 만들고 있어요...</p>
          )}
          {dedupeMessagesById(ideationConv?.messages).map((m) => <MessageBubble key={m.message_id} message={m} />)}
          {/* 스트리밍 임시 메시지 — message_start를 받는 즉시 말풍선이 생기고, 실제 LLM
              델타가 도착하는 대로 안에서 텍스트가 자란다(완성 후 재생하는 효과 아님).
              streamState는 최종 state 이벤트가 오면 즉시 비워지므로, 이 목록과 위
              ideationConv.messages가 같은 내용으로 동시에 남아 중복되는 순간은 없다. */}
          {streamState.messages.map((m) => (
            <MessageBubble key={m.message_id} message={m} streaming />
          ))}
          {sending && streamState.messages.length === 0 && (
            <p style={{ fontSize: 12.5, color: 'var(--text-2)' }}>
              {streamState.phaseLabel || `${statusLabelFor({ phase, starting, sending, finalizing })}...`}
            </p>
          )}
          {finalizing && (
            <p style={{ fontSize: 12.5, color: 'var(--text-2)' }}>
              {statusLabelFor({ phase, starting, sending, finalizing })}...
            </p>
          )}
          <div ref={chatEndRef} />
        </div>

        {ideationConv && phase !== 'finalized' && (
          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && canReplyOrContinue && handleSend()}
              placeholder={
                !canReplyOrContinue
                  ? '전문가 응답을 기다리는 중입니다'
                  : phase === 'awaiting_user_decision'
                    ? '필요하면 의견을 남겨주세요 (선택 사항)'
                    : '답변을 입력하세요'
              }
              disabled={!canReplyOrContinue}
              style={{ flex: 1, background: 'var(--bg-1)', border: '1px solid var(--glass-border)', borderRadius: 10, padding: '10px 14px', color: 'var(--text-0)', fontSize: 13 }}
            />
            <button className="btn-primary" style={{ padding: '10px 14px' }} disabled={!canReplyOrContinue || !draft.trim()} onClick={() => handleSend()}>
              <Send size={14} />
            </button>
          </div>
        )}

        {phase === 'awaiting_candidate_selection' && (
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button className="btn-ghost" style={{ fontSize: 12 }} disabled={!canReplyOrContinue} onClick={() => handleSend(REGENERATE_MESSAGE)}>
              다시 추천
            </button>
            <button className="btn-ghost" style={{ fontSize: 12 }} disabled={!canReplyOrContinue} onClick={() => handleSend(EXPERT_RECOMMEND_MESSAGE)}>
              전문가 추천
            </button>
          </div>
        )}
      </div>

      <div>
        <MergeAnalysisPanel
          mergeAnalysis={ideationConv?.merge_analysis}
          sourceCandidates={ideationConv?.source_candidates}
          userSelectionMessage={ideationConv?.user_selection_message}
        />

        {hasSelected ? (
          <div className="card glass" style={{ marginBottom: 12, padding: 14 }}>
            <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 6 }}>선택한 주제</div>
            <div style={{ fontSize: 13.5, fontWeight: 700, marginBottom: 4 }}>{ideationConv.selected_idea.title}</div>
            {ideationConv.selection_reason && (
              <div style={{ fontSize: 12, color: 'var(--text-2)', lineHeight: 1.6 }}>{ideationConv.selection_reason}</div>
            )}
          </div>
        ) : (
          hasCandidates && (
            <div style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 10, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                주제 후보
              </div>
              {ideationConv.idea_candidates.map((c, i) => (
                <CandidateCard key={c.candidate_id || i} candidate={c} index={i} onSelect={(idx) => handleSend(candidateSelectMessage(idx))} disabled={!canReplyOrContinue} />
              ))}
            </div>
          )
        )}

        {ideationConv && (ideationConv.consensus?.length > 0 || ideationConv.unresolved_issues?.length > 0) && (
          <div className="card glass" style={{ marginBottom: 12, padding: 14 }}>
            {ideationConv.consensus?.length > 0 && (
              <div style={{ marginBottom: 10 }}>
                <div style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--text-2)', marginBottom: 4 }}>합의 사항</div>
                <ul style={{ margin: 0, paddingLeft: 16, fontSize: 12, lineHeight: 1.7 }}>
                  {ideationConv.consensus.map((c, i) => <li key={i}>{c}</li>)}
                </ul>
              </div>
            )}
            {ideationConv.unresolved_issues?.length > 0 && (
              <div>
                <div style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--text-2)', marginBottom: 4 }}>미해결 쟁점</div>
                <ul style={{ margin: 0, paddingLeft: 16, fontSize: 12, lineHeight: 1.7 }}>
                  {ideationConv.unresolved_issues.map((u, i) => <li key={i}>{u}</li>)}
                </ul>
              </div>
            )}
          </div>
        )}

        <button className="btn-primary" style={{ width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }} disabled={!canFinalize} onClick={handleFinalize}>
          <Sparkles size={14} />
          {finalizing ? '초안 생성 중...' : '주제 확정하고 이어서 받기'}
        </button>
        {!canFinalize && ideationConv && phase !== 'finalized' && (
          <p style={{ fontSize: 11.5, color: 'var(--text-2)', marginTop: 8 }}>{nextActionGuideFor(phase)}</p>
        )}
      </div>
    </div>
  )
}

const PROPOSAL_ROWS = [
  ['problem_definition', '문제 정의'],
  ['target_user', '목표 사용자'],
  ['core_user_value', '핵심 사용자 가치'],
  ['key_features', '주요 기능'],
  ['required_data', '필요한 데이터'],
  ['tech_direction', '기술 구현 방향'],
  ['mvp_scope', 'MVP 범위'],
  ['differentiation', '차별성'],
  ['risks_and_mitigations', '위험 요소와 대응 방안'],
  ['success_metrics', '성공 지표'],
  ['expert_final_opinions', '전문가별 최종 판단'],
  ['unverified_assumptions', '검증이 필요한 가정'],
  ['final_recommendation', '최종 추천 여부'],
]

const NOT_FINALIZED = '아직 확정되지 않음'

function proposalValueDisplay(value) {
  if (value === null || value === undefined || value === '') return NOT_FINALIZED
  if (Array.isArray(value)) {
    if (value.length === 0) return NOT_FINALIZED
    return (
      <ul style={{ margin: 0, paddingLeft: 18, lineHeight: 1.7 }}>
        {value.map((item, i) => (
          <li key={i}>
            {typeof item === 'object' && item !== null
              ? [item.risk, item.mitigation].filter(Boolean).join(' → ') || JSON.stringify(item)
              : String(item)}
          </li>
        ))}
      </ul>
    )
  }
  if (typeof value === 'object') {
    return (
      <ul style={{ margin: 0, paddingLeft: 18, lineHeight: 1.7 }}>
        {Object.entries(value).map(([k, v]) => (
          <li key={k}>
            <strong style={{ fontWeight: 600 }}>{k}</strong> · {String(v)}
          </li>
        ))}
      </ul>
    )
  }
  return String(value)
}

export function IdeationResultScreen({ ideationConv, onBack }) {
  if (!ideationConv || ideationConv.phase !== 'finalized' || !ideationConv.idea_proposal) {
    return (
      <div style={{ maxWidth: 760 }}>
        <div className="badge amber mono" style={{ marginBottom: 12 }}>아직 확정되지 않음</div>
        <h2 style={{ fontSize: 20, fontWeight: 700, marginBottom: 16 }}>주제 발전 회의를 먼저 완료해 주세요</h2>
        <p style={{ fontSize: 13, color: 'var(--text-2)' }}>
          "주제 아이디어 회의" 단계에서 후보를 선택하고 전문가 질문에 답한 뒤, 확정 버튼을 눌러야 결과가 만들어져요.
        </p>
      </div>
    )
  }

  const proposal = ideationConv.idea_proposal
  const originalCandidates = ideationConv.original_idea_candidates || []
  const hasDiscoveryHistory = ideationConv.ideation_mode === 'discovery' && originalCandidates.length > 0

  return (
    <div style={{ maxWidth: 780 }}>
      <div className="badge green mono" style={{ marginBottom: 12 }}>주제 확정 · 기획서 작성 출발점</div>
      {onBack && (
        <button className="btn-ghost" style={{ marginBottom: 12, padding: '5px 10px', fontSize: 12 }} onClick={onBack}>
          ← 이전
        </button>
      )}
      <h2 style={{ fontSize: 22, fontWeight: 700, marginBottom: 20 }}>{proposal.idea_name || '확정된 주제'}</h2>

      <div className="card glass">
        {PROPOSAL_ROWS.map(([key, label], i) => (
          <div key={key} style={{ display: 'grid', gridTemplateColumns: '150px 1fr', gap: 16, padding: '14px 0', borderTop: i > 0 ? '1px solid var(--glass-border)' : 'none' }}>
            <div style={{ fontSize: 12, color: 'var(--text-2)', fontFamily: 'var(--mono)' }}>{label}</div>
            <div style={{ fontSize: 13.5, lineHeight: 1.6 }}>{proposalValueDisplay(proposal[key])}</div>
          </div>
        ))}
      </div>

      {hasDiscoveryHistory && (
        <div className="card glass" style={{ marginTop: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 12 }}>아이디어 발굴 이력</div>

          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--text-2)', marginBottom: 6 }}>최초 후보</div>
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, lineHeight: 1.7 }}>
              {originalCandidates.map((c) => <li key={c.candidate_id}>{c.title}</li>)}
            </ul>
          </div>

          {ideationConv.selected_idea && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--text-2)', marginBottom: 6 }}>선택하거나 결합한 후보</div>
              <div style={{ fontSize: 12.5, lineHeight: 1.6 }}>{ideationConv.selected_idea.title}</div>
            </div>
          )}

          {ideationConv.selection_reason && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--text-2)', marginBottom: 6 }}>선택 이유</div>
              <div style={{ fontSize: 12.5, lineHeight: 1.6 }}>{ideationConv.selection_reason}</div>
            </div>
          )}

          {ideationConv.user_selection_message && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--text-2)', marginBottom: 6 }}>사용자 원문 선택 요청</div>
              <div style={{ fontSize: 12.5, lineHeight: 1.6 }}>“{ideationConv.user_selection_message}”</div>
            </div>
          )}

          {ideationConv.merge_analysis && (
            <MergeAnalysisPanel mergeAnalysis={ideationConv.merge_analysis} sourceCandidates={ideationConv.source_candidates} />
          )}
        </div>
      )}
    </div>
  )
}
