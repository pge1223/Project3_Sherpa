function FileIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#5c86ac" strokeWidth="1.8">
      <path d="M6 2.5h8l4 4V20a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 20V4a1.5 1.5 0 0 1 1.5-1.5Z" />
      <path d="M14 2.5V7h4.5" />
    </svg>
  )
}

function LinkIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#5c86ac" strokeWidth="1.8">
      <path d="M9.5 14.5 14.5 9.5" />
      <path d="M11 6.5 12.5 5a3.5 3.5 0 0 1 5 5L16 11.5" />
      <path d="M13 17.5 11.5 19a3.5 3.5 0 0 1-5-5L8 12.5" />
    </svg>
  )
}

export default function DocumentRow({ document }) {
  return (
    <div style={styles.row}>
      <div style={styles.left}>
        {document.type === 'url' ? <LinkIcon /> : <FileIcon />}
        <div>
          <div style={styles.name}>{document.name}</div>
          <div style={styles.meta}>{document.meta}</div>
        </div>
      </div>

      {document.status === 'embedding' && (
        <div style={styles.progressWrap}>
          <div style={styles.progressTrack}>
            <div style={{ ...styles.progressFill, width: `${document.progress}%` }} />
          </div>
          <span style={styles.progressLabel}>임베딩 중</span>
        </div>
      )}

      {document.status === 'done' && <span style={styles.doneBadge}>✓ 완료</span>}
    </div>
  )
}

const styles = {
  row: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '14px 4px',
  },
  left: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
  },
  name: {
    fontSize: 14,
    fontWeight: 600,
    color: '#17324a',
  },
  meta: {
    fontSize: 12,
    color: '#7994ac',
    marginTop: 2,
  },
  progressWrap: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
  },
  progressTrack: {
    width: 100,
    height: 6,
    borderRadius: 999,
    background: '#e2edf7',
    overflow: 'hidden',
  },
  progressFill: {
    height: '100%',
    background: '#2f7fd1',
    borderRadius: 999,
  },
  progressLabel: {
    fontSize: 12,
    color: '#7994ac',
  },
  doneBadge: {
    fontSize: 12,
    fontWeight: 600,
    color: '#1f8a4c',
    background: '#dcf3e6',
    padding: '4px 10px',
    borderRadius: 999,
  },
}
