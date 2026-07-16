import { useNavigate } from 'react-router-dom'

// 가은/Claude(2026-07-16): MentorSelectionPage/FeedbackProgressPage에 똑같이 복붙돼 있던
// 8단계 사이드바를 공통 컴포넌트로 뺐다 — 화면 확인용으로 클릭해서 바로 이동할 수 있게
// 해달라는 요청.
// 가은/Claude(2026-07-17): 원래 "정보입력"/"문서첨부"를 별도 단계로 나눠뒀었는데, 실제로는
// DocumentUploadPage 한 화면이 둘 다 같이 처리하고 있어서(같은 route) 굳이 사이드바에서
// 두 단계로 보일 이유가 없다는 사용자 지적으로 하나로 합쳤다 — 8단계 -> 7단계.
// 1번 "아바타 안내"는 실제로 안 만들기로 해서 라우트가 없었는데(클릭 비활성), 사용자 요청으로
// 그 자리를 프로젝트 목록(ProjectListPage) 이동 단계로 바꿨다 — 자리만 바꾼 1:1 교체라
// 총 7단계, 다른 단계들의 activeIndex는 그대로 유지된다.
// projectId가 있으면 ?projectId= 쿼리로 넘겨서 그 프로젝트를 이어서 보여주고
// (DocumentUploadPage가 처리), 없으면(아직 프로젝트가 없는 첫 진입) 그냥 새로 시작한다.
// 가은/Claude(2026-07-17): STEP6 "대화형 피드백"은 원래 영상 시뮬레이션 전용 페이지
// (/simulation, MeetingSimulationPage)로 연결돼 있었는데, 목업대로 텍스트 Q&A 화면
// (/feedback-chat, MentorFeedbackChatPage)을 새로 만든 뒤 사용자 요청으로 영상
// (CommitteeVideoStage)도 이 화면 상단으로 옮겨왔다 — /simulation 라우트는 없앴고,
// 영상+대화를 한 화면에서 같이 보여준다.
export function buildSteps(projectId) {
  const uploadRoute = projectId ? `/projects/new?projectId=${projectId}` : '/projects/new'
  return [
    { title: '내 프로젝트', subtitle: '프로젝트 목록', route: '/projects' },
    { title: '공모전 정보 입력 · 문서 첨부', subtitle: '기본 정보 & 기획서 업로드', route: uploadRoute },
    { title: '공모전 분석', subtitle: '전문가 멘토 추천', route: `/projects/${projectId}/analysis` },
    { title: '멘토 선택', subtitle: '2~4명 선택', route: `/projects/${projectId}/analysis` },
    { title: '피드백 진행', subtitle: '검토 중', route: `/projects/${projectId}/progress` },
    { title: '대화형 피드백', subtitle: '추가 질문', route: `/projects/${projectId}/feedback-chat` },
    { title: '결과 정리', subtitle: '최종 리포트', route: `/projects/${projectId}` },
  ]
}

// activeIndex: 현재 화면에 해당하는 STEPS 인덱스(0-based). done은 activeIndex보다 앞선
// 단계에 자동으로 매겨진다 — 실제 진행 여부를 추적하는 게 아니라 "여기까진 지나왔다"는
// 시각적 표시일 뿐이다(화면 확인용 이동 자체를 막지는 않는다).
export default function StepSidebar({ projectId, activeIndex }) {
  const navigate = useNavigate()
  const steps = buildSteps(projectId)

  return (
    <aside style={styles.sidebar}>
      <div style={styles.brand}>
        <div style={styles.brandIcon}>📋</div>
        <div>
          <div style={styles.brandTitle}>AI Review Board</div>
          <div style={styles.brandSubtitle}>공모전 피드백 서비스</div>
        </div>
      </div>
      <div style={styles.stepList}>
        {steps.map((step, i) => {
          const isActive = i === activeIndex
          const isDone = i < activeIndex
          const clickable = !!step.route && !isActive
          return (
            <button
              key={step.title}
              onClick={() => clickable && navigate(step.route)}
              disabled={!clickable}
              style={{
                ...styles.stepRow,
                cursor: clickable ? 'pointer' : 'default',
                opacity: step.route ? 1 : 0.5,
              }}
            >
              <div
                style={{
                  ...styles.stepBadge,
                  ...(isDone ? styles.stepBadgeDone : {}),
                  ...(isActive ? styles.stepBadgeActive : {}),
                }}
              >
                {isDone ? '✓' : i + 1}
              </div>
              <div>
                <div style={{ ...styles.stepTitle, ...(isActive ? styles.stepTitleActive : {}) }}>
                  {step.title}
                </div>
                <div style={styles.stepSubtitle}>{step.subtitle}</div>
              </div>
            </button>
          )
        })}
      </div>
    </aside>
  )
}

const ACCENT = '#7c4dff'

const styles = {
  sidebar: {
    borderRight: '1px solid #ece9f7',
    background: '#fff',
    padding: '20px 16px',
  },
  brand: { display: 'flex', alignItems: 'center', gap: 10, marginBottom: 24 },
  brandIcon: {
    width: 36,
    height: 36,
    borderRadius: 10,
    background: ACCENT,
    color: '#fff',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 16,
  },
  brandTitle: { fontSize: 14, fontWeight: 700 },
  brandSubtitle: { fontSize: 11, color: '#8b8fa3' },
  stepList: { display: 'flex', flexDirection: 'column', gap: 4 },
  stepRow: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: 10,
    background: 'none',
    border: 'none',
    padding: '6px 4px',
    borderRadius: 8,
    textAlign: 'left',
    font: 'inherit',
    color: 'inherit',
    width: '100%',
  },
  stepBadge: {
    width: 24,
    height: 24,
    borderRadius: '50%',
    background: '#eee',
    color: '#8b8fa3',
    fontSize: 12,
    fontWeight: 700,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  stepBadgeDone: { background: '#e3f6e9', color: '#1f8a4c' },
  stepBadgeActive: { background: ACCENT, color: '#fff' },
  stepTitle: { fontSize: 13, fontWeight: 600, color: '#4b4f63' },
  stepTitleActive: { color: ACCENT },
  stepSubtitle: { fontSize: 11, color: '#a1a5b8' },
}
