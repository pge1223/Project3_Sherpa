import { useEffect, useRef, useState } from 'react'
import { AlertCircle, ChevronDown, ChevronUp, RefreshCw, Send, Sparkles } from 'lucide-react'
import {
  finalizeIdeationConversation,
  getIdeationConversation,
  replyIdeationConversation,
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

// 가은/Claude(2026-07-21): 실측 요청 — 백엔드가 전체 응답을 한 번에 돌려주는 REST
// 호출이라(스트리밍 없음) 도착한 텍스트를 한 글자씩 풀어내는 클라이언트 사이드
// 타이핑 효과만 낸다(진짜 토큰 스트리밍이 아니다). 이미 화면에 있던 메시지(이전 단계
// 갔다 돌아오거나 세션을 이어받은 경우)까지 다시 타이핑되면 어색하므로, "새로 도착한"
// 위원 메시지에만 적용한다 — 어디서 이 구분을 하고, 여러 버블이 같이 왔을 때 어떻게
// 순서대로(앞 버블이 끝나야 다음 버블) 치는지는 IdeationScreen의 animation/processedCount
// 참고. onComplete는 이 버블 타이핑이 끝났을 때 호출돼 다음 버블 차례로 넘긴다.
function useTypewriter(text, enabled, onComplete) {
  const [display, setDisplay] = useState(enabled ? '' : text)
  const [done, setDone] = useState(!enabled)
  // onComplete는 렌더마다 새로 만들어지는(인라인 화살표) 콜백이라 effect deps에 넣으면
  // 애니메이션이 매번 재시작된다 — ref로 최신 값만 참조하고 deps에서는 뺀다.
  const onCompleteRef = useRef(onComplete)
  onCompleteRef.current = onComplete

  useEffect(() => {
    if (!enabled) {
      setDisplay(text)
      setDone(true)
      return
    }
    setDisplay('')
    setDone(false)
    if (!text) {
      setDone(true)
      // 내용이 빈(오류) 위원 메시지도 타이핑 큐에서 즉시 다음으로 넘어가게 완료를 알린다.
      onCompleteRef.current?.()
      return
    }
    let i = 0
    // 가은/Claude(2026-07-21): 타이핑을 조금 더 천천히(요청). 틱 간격을 늘리고, 긴 답변도
    // 과하게 오래 걸리지 않도록 잡아두는 글자수 상한(길이/N)의 N을 키웠다 — 짧은 답변은
    // 틱 간격만큼, 긴 답변은 대략 (N × 틱 간격)만큼 걸린다.
    const CHARS_PER_TICK = Math.max(1, Math.ceil(text.length / 150))
    const timer = setInterval(() => {
      i += CHARS_PER_TICK
      if (i >= text.length) {
        setDisplay(text)
        setDone(true)
        clearInterval(timer)
        // 이 버블의 타이핑이 끝났음을 부모에게 알려 다음 버블 타이핑을 시작하게 한다.
        onCompleteRef.current?.()
      } else {
        setDisplay(text.slice(0, i))
      }
    }, 28)
    return () => clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, enabled])

  return { display, done }
}

function MessageBubble({ message, typing, hidden, onComplete }) {
  const meta = speakerMetaFor(message)
  const isRight = meta.align === 'right'
  const hasContent = !!message.content?.trim()
  const { display, done } = useTypewriter(message.content || '', typing, onComplete)

  // 앞 버블이 아직 타이핑 중이라 순서가 오지 않은 위원 버블 — 아직 화면에 띄우지 않는다
  // (실제 채팅처럼 차례가 오면 그때 나타난다). 훅은 위에서 이미 다 호출한 뒤라 순서 안전.
  if (hidden) return null

  if (!hasContent) {
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
          {display}
          {typing && !done && <span className="rb-typing-cursor">▌</span>}
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

  const startedRef = useRef(false)
  const chatEndRef = useRef(null)

  // 가은/Claude(2026-07-21): 타이핑 효과는 "새로 도착한" 위원 메시지에만 건다 — 마운트
  // 시점(세션을 이어받아 이미 대화 내역이 있는 경우 포함)에 있던 메시지는 전부
  // "이미 본 것"으로 미리 표시해 다시 타이핑되지 않게 한다.
  //
  // 가은/Claude(2026-07-21, 순차 타이핑): 한 턴에 진행자·기획 위원 두 버블이 같이
  // 도착하면 예전엔 두 버블이 동시에 타이핑됐다. 진짜 채팅처럼 앞 버블(진행자)이 다
  // 쳐지고 나서 다음 버블(기획 위원)이 이어서 쳐지도록, 새로 도착한 위원 메시지들을
  // 도착 순서대로 큐(animation.ids)에 담고 지금 칠 차례인 하나(animation.index)만
  // 타이핑하게 한다. 큐보다 뒤 차례인 버블은 차례가 올 때까지 화면에 띄우지 않는다.
  const currentMessages = ideationConv?.messages || []
  const [animation, setAnimation] = useState(null) // { ids: string[], index: number } | null

  // 렌더 도중 "직전 렌더 대비 새로 붙은 메시지"를 감지해 타이핑 큐를 세팅한다(React의
  // "렌더 중 state 조정" 패턴). effect가 아니라 렌더에서 하므로 새 버블이 한 번이라도
  // 완성본(typing=false)으로 커밋됐다가 다시 지워지며 타이핑되는 깜빡임이 없다.
  // messages는 항상 뒤에 append되므로 processedCount 이후 꼬리만 새 메시지다. 마운트
  // 시점(=이어받은 세션)에 있던 메시지는 processedCount 초깃값에 포함돼 타이핑되지 않는다.
  const [processedCount, setProcessedCount] = useState(currentMessages.length)
  if (currentMessages.length !== processedCount) {
    const appended = currentMessages.slice(processedCount)
    const newCommitteeIds = appended.filter((m) => m.speaker_id !== 'user').map((m) => m.message_id)
    setProcessedCount(currentMessages.length)
    setAnimation(newCommitteeIds.length > 0 ? { ids: newCommitteeIds, index: 0 } : null)
  }

  // 지금 칠 차례의 버블이 끝나면 다음 차례로 넘어가고, 마지막까지 끝나면 큐를 비운다.
  function advanceTyping() {
    setAnimation((a) => {
      if (!a) return a
      const next = a.index + 1
      return next >= a.ids.length ? null : { ...a, index: next }
    })
  }

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
  }, [ideationConv?.messages?.length, animation?.index])

  const phase = ideationConv?.phase
  const busy = starting || sending || finalizing || saving
  // awaiting_user_decision도 입력을 막지 않는다("더 이야기하기") — 백엔드
  // apply_user_answer가 이 경우도 받아 두 전문가 보완 의견으로 이어간다.
  const canReplyOrContinue = !!ideationConv && REPLYABLE_PHASES.has(phase) && !busy
  const canFinalize = !!ideationConv && phase === 'awaiting_user_decision' && !busy
  const hasCandidates = (ideationConv?.idea_candidates?.length || 0) > 0
  const hasSelected = !!ideationConv?.selected_idea

  async function handleSend(overrideText) {
    const text = (overrideText ?? draft).trim()
    if (!text || !ideationConv || !canReplyOrContinue) return
    setSending(true)
    setError(null)
    try {
      const data = await replyIdeationConversation(ideationConv.session_id, text)
      setIdeationConv(data)
      setDraft('')
    } catch (err) {
      setError(classifyIdeationConvError(err))
    } finally {
      setSending(false)
    }
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
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
          {onBack && (
            <button
              className="btn-ghost"
              style={{ padding: '2px 8px', fontSize: 15, fontWeight: 700, color: '#000', border: 'none', background: 'transparent' }}
              onClick={onBack}
              disabled={busy}
              aria-label="이전 화면으로 이동"
            >
              {'<'}
            </button>
          )}
          <div className="badge coral mono">주제 아이디어 회의</div>
        </div>
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

        <div className="card glass" style={{ minHeight: 360, maxHeight: 520, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4, padding: 16 }}>
          {starting && !ideationConv && (
            <p style={{ color: 'var(--text-2)', fontSize: 13 }}>공모전 분석을 바탕으로 아이디어 후보를 만들고 있어요...</p>
          )}
          {currentMessages.map((m) => {
            const animPos = animation ? animation.ids.indexOf(m.message_id) : -1
            return (
              <MessageBubble
                key={m.message_id}
                message={m}
                typing={animPos !== -1 && animPos === animation.index}
                hidden={animPos !== -1 && animPos > animation.index}
                onComplete={advanceTyping}
              />
            )
          })}
          {(sending || finalizing) && (
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
              placeholder={canReplyOrContinue ? '답변을 입력하세요' : '전문가 응답을 기다리는 중입니다'}
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
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        {onBack && (
          <button
            className="btn-ghost"
            style={{ padding: '2px 8px', fontSize: 15, fontWeight: 700, color: '#000', border: 'none', background: 'transparent' }}
            onClick={onBack}
            aria-label="이전 화면으로 이동"
          >
            {'<'}
          </button>
        )}
        <div className="badge green mono">주제 확정 · 기획서 작성 출발점</div>
      </div>
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
