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
