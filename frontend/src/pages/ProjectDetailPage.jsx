import { useParams } from 'react-router-dom'

export default function ProjectDetailPage() {
  const { projectId } = useParams()

  return (
    <div
      style={{
        minHeight: '100vh',
        background: 'linear-gradient(180deg, #dceefc 0%, #eaf3fb 100%)',
        color: '#17324a',
        padding: 48,
      }}
    >
      <h1 style={{ color: '#1a3a5c' }}>프로젝트 상세: {projectId}</h1>
      <p style={{ color: '#7994ac' }}>다음 화면은 여기서 이어서 만들면 됩니다.</p>
    </div>
  )
}
