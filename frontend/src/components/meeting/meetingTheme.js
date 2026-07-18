// 위원 발언 색상은 dataviz 스킬의 categorical 팔레트에서 고정 순서로 배정한다(순환 금지).
// 배경(#eaf3fb) 기준 검증 결과 aqua/yellow는 3:1 미만이라 색만으로 구분하지 않고
// 이름 라벨을 항상 함께 노출한다(relief rule).
const PERSONA_COLORS = {
  business_strategy: '#2a78d6', // slot1 blue
  technical_feasibility: '#1baf7a', // slot2 aqua
  creativity_originality: '#eda100', // slot3 yellow
  presentation_completeness: '#008300', // slot4 green
  review_chair: '#4a3aa7', // slot5 violet — 위원장은 별도 슬롯으로 구분
}
const FALLBACK_COLOR = '#5c86ac'

export function personaColor(personaId) {
  return PERSONA_COLORS[personaId] ?? FALLBACK_COLOR
}

export function personaInitial(name) {
  return (name || '?').trim().charAt(0)
}

// judgment(6종) -> 상태 배지. strong/acceptable은 긍정, needs_improvement는 경고,
// critical_risk는 위험, insufficient_evidence/not_applicable은 "판단 보류"로 중립 처리한다.
// (기존 앱의 완료/실패 배지 색과 맞춰 good=#1f8a4c, critical=#d64545을 그대로 쓰고,
// warning만 앱에 없던 색이라 dataviz 상태 팔레트의 warning을 가져왔다.)
const JUDGMENT_CONFIG = {
  strong: { label: '우수', bg: '#dcf3e6', color: '#1f8a4c' },
  acceptable: { label: '양호', bg: '#dcf3e6', color: '#1f8a4c' },
  needs_improvement: { label: '보완 필요', bg: '#fdf1d6', color: '#9a6400' },
  critical_risk: { label: '핵심 리스크', bg: '#fbe2e2', color: '#d64545' },
  insufficient_evidence: { label: '근거 부족', bg: '#eef1f4', color: '#7994ac' },
  not_applicable: { label: '해당 없음', bg: '#eef1f4', color: '#7994ac' },
}
const FALLBACK_JUDGMENT = { label: '미정', bg: '#eef1f4', color: '#7994ac' }

export function judgmentBadge(judgment) {
  return JUDGMENT_CONFIG[judgment] ?? FALLBACK_JUDGMENT
}

// media_script(재인님 영상용 대사)가 있으면 그대로 회의 발언 순서로 쓰고,
// 없으면 reviewer_results + chair_summary로 즉석에서 같은 형태를 만든다.
// MeetingChat(채팅 로그)과 MeetingSimulationPage(영상 시뮬레이션)가 같은 발언 순서를
// 공유해야 해서 여기(공통 파일)로 뺐다.
export function buildTranscript(result) {
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

  // 가은/Claude(2026-07-17): 사용자 요청 — 발언 시작을 위원의 전반적 요약(summary)이
  // 아니라 기준별 실행 가능한 제안(rubric_scores[].suggestions)으로 보여준다. 한
  // 위원이 여러 기준을 검토하므로 배열의 배열이라, flatMap으로 위원당 하나의 배열로
  // 모은 뒤 한 문단으로 이어붙인다. suggestions가 비어있는 예외 상황엔 summary로
  // 폴백해 빈 말풍선을 막는다.
  const reviewerLines = (result.reviewer_results || []).map((r) => {
    const suggestions = (r.rubric_scores || []).flatMap((rs) => rs.suggestions || [])
    return {
      personaId: r.persona_id,
      speakerName: r.persona_name,
      role: r.role,
      text: suggestions.length > 0 ? suggestions.join(' ') : r.summary,
      emotion: null,
    }
  })

  return chairLine ? [...reviewerLines, chairLine] : reviewerLines
}
