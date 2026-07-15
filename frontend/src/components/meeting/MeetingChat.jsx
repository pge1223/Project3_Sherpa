import { personaColor, personaInitial, judgmentBadge } from './meetingTheme'

function Avatar({ name, personaId }) {
  const color = personaColor(personaId)
  return (
    <div
      style={{
        ...styles.avatar,
        background: `${color}22`,
        color,
        border: `1.5px solid ${color}55`,
      }}
    >
      {personaInitial(name)}
    </div>
  )
}

function ChatBubble({ speakerName, role, text, personaId, emotion }) {
  const color = personaColor(personaId)
  return (
    <div style={styles.bubbleRow}>
      <Avatar name={speakerName} personaId={personaId} />
      <div style={styles.bubbleBody}>
        <div style={styles.bubbleHeader}>
          <span style={{ ...styles.speakerName, color }}>{speakerName}</span>
          {role && role !== speakerName && <span style={styles.speakerRole}>{role}</span>}
          {emotion && <span style={styles.emotionTag}>{emotion}</span>}
        </div>
        <div style={{ ...styles.bubble, borderColor: `${color}33` }}>{text}</div>
      </div>
    </div>
  )
}

// media_script(재인님 영상용 대사)가 있으면 그대로 회의 발언 순서로 쓰고,
// 없으면 reviewer_results + chair_summary로 즉석에서 같은 형태를 만든다.
function buildTranscript(result) {
  const chairLine = result.chair_summary
    ? {
        personaId: 'review_chair',
        speakerName: '위원장',
        role: null,
        text: result.chair_summary.overall_assessment,
        emotion: null,
      }
    : null

  if (Array.isArray(result.media_script) && result.media_script.length > 0) {
    const lines = [...result.media_script]
      .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
      .map((line) => ({
        personaId: line.speaker_id,
        speakerName: line.speaker_name,
        role: null,
        text: line.text,
        emotion: line.emotion,
      }))
    // media_script는 위원 발언 위주(영상 대본용)라 위원장 종합이 빠져 있을 수 있다 —
    // "회의" 형태를 완성하려면 위원장 발언이 꼭 있어야 하므로 없으면 마지막에 보강한다.
    const hasChairLine = lines.some((l) => l.personaId === 'review_chair')
    return hasChairLine || !chairLine ? lines : [...lines, chairLine]
  }

  const reviewerLines = (result.reviewer_results || []).map((r) => ({
    personaId: r.persona_id,
    speakerName: r.persona_name,
    role: r.role,
    text: r.summary,
    emotion: null,
  }))

  return chairLine ? [...reviewerLines, chairLine] : reviewerLines
}

function ScoreBar({ label, score, maxScore }) {
  const pct = maxScore ? Math.round((score / maxScore) * 100) : 0
  return (
    <div style={styles.scoreRow}>
      <div style={styles.scoreLabel}>{label}</div>
      <div style={styles.scoreTrack}>
        <div style={{ ...styles.scoreFill, width: `${pct}%` }} />
      </div>
      <div style={styles.scoreValue}>
        {score}/{maxScore}
      </div>
    </div>
  )
}

function RubricDetail({ reviewer }) {
  return (
    <details style={styles.details}>
      <summary style={styles.detailsSummary}>
        {reviewer.persona_name} 위원의 평가 근거 ({reviewer.rubric_scores?.length ?? 0}개 항목)
      </summary>
      {(reviewer.rubric_scores || []).map((s) => {
        const badge = judgmentBadge(s.judgment)
        return (
          <div key={s.criterion_id} style={styles.criterionBlock}>
            <div style={styles.criterionHeader}>
              <span style={styles.criterionName}>{s.criterion_name}</span>
              <span style={{ ...styles.judgmentBadge, background: badge.bg, color: badge.color }}>
                {badge.label}
              </span>
              {s.score != null && (
                <span style={styles.criterionScore}>
                  {s.score}/{s.max_score}점
                </span>
              )}
            </div>
            {s.strengths?.length > 0 && (
              <div style={styles.criterionLine}>
                <b style={styles.strengthLabel}>+</b> {s.strengths.join(' · ')}
              </div>
            )}
            {s.issues?.length > 0 && (
              <div style={styles.criterionLine}>
                <b style={styles.issueLabel}>-</b> {s.issues.join(' · ')}
              </div>
            )}
            {s.suggestions?.length > 0 && (
              <div style={styles.criterionLine}>
                <b style={styles.suggestionLabel}>→</b> {s.suggestions.join(' · ')}
              </div>
            )}
          </div>
        )
      })}
    </details>
  )
}

export default function MeetingChat({ result }) {
  if (!result) return null
  const transcript = buildTranscript(result)
  const score = result.score_result

  return (
    <div>
      <div style={styles.transcript}>
        {transcript.map((line, i) => (
          <ChatBubble key={i} {...line} />
        ))}
      </div>

      {score && (
        <div style={styles.card}>
          <h2 style={styles.sectionTitle}>
            종합 점수 {score.total_score}/{score.max_score}
          </h2>
          {(score.breakdown || []).map((b) => {
            const criterion = result.rubric?.criteria?.find((c) => c.criterion_id === b.criterion_id)
            return (
              <ScoreBar
                key={b.criterion_id}
                label={criterion?.criterion_name ?? b.criterion_id}
                score={b.weighted_score}
                maxScore={b.max_score}
              />
            )
          })}
        </div>
      )}

      {(result.reviewer_results || []).length > 0 && (
        <div style={styles.card}>
          <h2 style={styles.sectionTitle}>위원별 평가 근거</h2>
          {result.reviewer_results.map((r) => (
            <RubricDetail key={r.review_id ?? r.persona_id} reviewer={r} />
          ))}
        </div>
      )}

      {result.top_revisions?.length > 0 && (
        <div style={styles.card}>
          <h2 style={styles.sectionTitle}>수정 우선순위</h2>
          <ol style={styles.revisionList}>
            {result.top_revisions.map((rev) => (
              <li key={rev.priority} style={styles.revisionItem}>
                <div style={styles.revisionTitle}>{rev.title}</div>
                <div style={styles.revisionMeta}>대상: {rev.target}</div>
                <div style={styles.revisionAction}>{rev.action}</div>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  )
}

const styles = {
  transcript: {
    display: 'flex',
    flexDirection: 'column',
    gap: 18,
  },
  bubbleRow: {
    display: 'flex',
    gap: 12,
    alignItems: 'flex-start',
  },
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
  bubbleBody: { flex: 1, minWidth: 0 },
  bubbleHeader: {
    display: 'flex',
    alignItems: 'baseline',
    gap: 8,
    marginBottom: 4,
  },
  speakerName: { fontWeight: 700, fontSize: 14 },
  speakerRole: { fontSize: 12, color: '#7994ac' },
  emotionTag: {
    fontSize: 11,
    color: '#7994ac',
    background: '#eef1f4',
    padding: '1px 8px',
    borderRadius: 999,
  },
  bubble: {
    background: '#fff',
    border: '1px solid #d9e8f5',
    borderRadius: '4px 14px 14px 14px',
    padding: '10px 14px',
    fontSize: 14,
    lineHeight: 1.55,
    color: '#17324a',
  },
  card: {
    background: '#fff',
    border: '1px solid #d9e8f5',
    borderRadius: 12,
    padding: 20,
    marginTop: 20,
  },
  sectionTitle: { margin: '0 0 14px', fontSize: 16, color: '#1a3a5c' },
  scoreRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    marginBottom: 10,
  },
  scoreLabel: { width: 140, fontSize: 13, color: '#334', flexShrink: 0 },
  scoreTrack: {
    flex: 1,
    height: 8,
    borderRadius: 999,
    background: '#e2edf7',
    overflow: 'hidden',
  },
  scoreFill: { height: '100%', background: '#2f7fd1', borderRadius: 999 },
  scoreValue: { width: 56, textAlign: 'right', fontSize: 13, color: '#334', flexShrink: 0 },
  details: {
    borderTop: '1px solid #eef1f4',
    padding: '10px 0',
  },
  detailsSummary: {
    cursor: 'pointer',
    fontSize: 14,
    fontWeight: 600,
    color: '#1a3a5c',
  },
  criterionBlock: { marginTop: 10, paddingLeft: 4 },
  criterionHeader: { display: 'flex', alignItems: 'center', gap: 8 },
  criterionName: { fontSize: 13, fontWeight: 600, color: '#17324a' },
  judgmentBadge: {
    fontSize: 11,
    fontWeight: 600,
    padding: '2px 8px',
    borderRadius: 999,
  },
  criterionScore: { fontSize: 12, color: '#7994ac' },
  criterionLine: { fontSize: 13, color: '#455a70', marginTop: 4, lineHeight: 1.5 },
  strengthLabel: { color: '#1f8a4c' },
  issueLabel: { color: '#d64545' },
  suggestionLabel: { color: '#2f7fd1' },
  revisionList: { margin: 0, paddingLeft: 20 },
  revisionItem: { marginBottom: 14 },
  revisionTitle: { fontSize: 14, fontWeight: 700, color: '#1a3a5c' },
  revisionMeta: { fontSize: 12, color: '#7994ac', marginTop: 2 },
  revisionAction: { fontSize: 13, color: '#334', marginTop: 4, lineHeight: 1.5 },
}
