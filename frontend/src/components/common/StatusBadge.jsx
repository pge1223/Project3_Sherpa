const STATUS_CONFIG = {
  reviewed: { label: '검토 완료', bg: '#dcf3e6', color: '#1f8a4c' },
  in_progress: { label: '진행 중', bg: '#dbeafe', color: '#1d5fae' },
  pending: { label: '대기', bg: null, color: '#8ba0b3' },
}

export default function StatusBadge({ status }) {
  const config = STATUS_CONFIG[status] ?? STATUS_CONFIG.pending

  return (
    <span
      style={{
        display: 'inline-block',
        padding: config.bg ? '4px 12px' : 0,
        borderRadius: 999,
        background: config.bg ?? 'transparent',
        color: config.color,
        fontSize: 13,
        fontWeight: 500,
      }}
    >
      {config.label}
    </span>
  )
}
