// 가은/Claude(2026-07-23, 요청: 문서별 색인 로딩바 — 여러 화면에서 재사용): 문서
// 업로드/URL 색인처럼 "진행 중"을 보여줘야 하는 곳마다 막대를 새로 그리던 걸(DocumentRow.jsx,
// ReviewBoardPrototype.jsx 문서 목록 등) 한 컴포넌트로 뺐다. percent만 넘기면 되고, 필요하면
// label/색/두께/트랙 너비를 덮어쓸 수 있다.
export default function ProgressBar({
  percent,
  label,
  color = '#7c4dff',
  trackColor = '#f0eefc',
  height = 6,
  // 기본은 문서 행처럼 좁은 자리에 맞춘 고정 100px. fill=true면(예: 로딩 화면 전체 너비
  // 카드) 옆의 label 자리를 뺀 나머지를 다 채운다 — 둘 다 flex 안에서 쓰여도 서로
  // 자리를 침범하지 않도록 track의 flex 속성 자체를 바꾼다(고정폭은 줄어들지 않게,
  // fill은 늘어나게).
  fill = false,
}) {
  const clamped = Math.max(0, Math.min(100, percent ?? 0))
  return (
    <div style={styles.wrap}>
      <div
        style={{
          ...styles.track,
          height,
          background: trackColor,
          ...(fill ? styles.trackFill : { width: 100, flexShrink: 0 }),
        }}
      >
        <div style={{ ...styles.fill, width: `${clamped}%`, background: color }} />
      </div>
      {label && <span style={styles.label}>{label}</span>}
    </div>
  )
}

const styles = {
  wrap: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
  },
  track: {
    borderRadius: 999,
    overflow: 'hidden',
  },
  trackFill: {
    flex: '1 1 auto',
    minWidth: 0,
  },
  fill: {
    height: '100%',
    borderRadius: 999,
    transition: 'width 0.4s ease',
  },
  label: {
    fontSize: 12,
    color: '#8b8fa3',
    whiteSpace: 'nowrap',
  },
}
