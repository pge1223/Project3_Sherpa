import ProgressBar from '../common/ProgressBar'

function FileIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#7c4dff" strokeWidth="1.8">
      <path d="M6 2.5h8l4 4V20a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 20V4a1.5 1.5 0 0 1 1.5-1.5Z" />
      <path d="M14 2.5V7h4.5" />
    </svg>
  )
}

function LinkIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#7c4dff" strokeWidth="1.8">
      <path d="M9.5 14.5 14.5 9.5" />
      <path d="M11 6.5 12.5 5a3.5 3.5 0 0 1 5 5L16 11.5" />
      <path d="M13 17.5 11.5 19a3.5 3.5 0 0 1-5-5L8 12.5" />
    </svg>
  )
}

// 가은/Claude(2026-07-18): URL 공고문에 HWP 첨부파일이 있어 자동으로 못 읽은 경우
// (실측: sotong.go.kr — 평가기준이 본문이 아니라 HWP 요강 파일에만 있는 공고가 실제로
// 있었음), 사용자가 그 파일을 원본 사이트에서 직접 받아 "파일 업로드" 탭(HWP 직접
// 업로드는 LibreOffice 변환으로 이미 지원됨)으로 올릴 수 있게 다운로드 링크를 보여준다.
export default function DocumentRow({ document }) {
  const links = document.unsupportedLinks || []
  return (
    <div style={styles.container}>
      <div style={styles.row}>
        <div style={styles.left}>
          {document.type === 'url' ? <LinkIcon /> : <FileIcon />}
          <div>
            <div style={styles.name}>{document.name}</div>
            <div style={styles.meta}>{document.meta}</div>
          </div>
        </div>

        {document.status === 'embedding' && (
          <ProgressBar percent={document.progress} label="임베딩 중" />
        )}

        {document.status === 'done' && <span style={styles.doneBadge}>✓ 완료</span>}
        {document.status === 'warning' && <span style={styles.warningBadge}>⚠ 확인 필요</span>}
        {document.status === 'error' && <span style={styles.errorBadge}>업로드 실패</span>}
      </div>

      {links.length > 0 && (
        <div style={styles.linkList}>
          {links.map((link, i) => (
            <a
              key={link.url}
              href={link.url}
              target="_blank"
              rel="noopener noreferrer"
              style={styles.linkItem}
            >
              첨부파일 {i + 1} 받기 (HWP) ↗
            </a>
          ))}
        </div>
      )}
    </div>
  )
}

const styles = {
  container: {
    padding: '14px 4px',
  },
  row: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  linkList: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: 8,
    paddingLeft: 32,
  },
  linkItem: {
    fontSize: 12,
    fontWeight: 600,
    color: '#7c4dff',
    background: '#f0eefc',
    padding: '4px 10px',
    borderRadius: 999,
    textDecoration: 'none',
  },
  left: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
  },
  name: {
    fontSize: 14,
    fontWeight: 600,
    color: '#1f2333',
  },
  meta: {
    fontSize: 12,
    color: '#8b8fa3',
    marginTop: 2,
  },
  doneBadge: {
    fontSize: 12,
    fontWeight: 600,
    color: '#1f8a4c',
    background: '#dcf3e6',
    padding: '4px 10px',
    borderRadius: 999,
  },
  errorBadge: {
    fontSize: 12,
    fontWeight: 600,
    color: '#d64545',
    background: '#fbe2e2',
    padding: '4px 10px',
    borderRadius: 999,
  },
  warningBadge: {
    fontSize: 12,
    fontWeight: 600,
    color: '#9a6400',
    background: '#fdf1d6',
    padding: '4px 10px',
    borderRadius: 999,
  },
}
