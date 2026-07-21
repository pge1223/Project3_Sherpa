import { Routes, Route } from 'react-router-dom'
import LandingPage from './pages/LandingPage'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import MyPage from './pages/MyPage'
import ProjectListPage from './pages/ProjectListPage'
import ProjectDetailPage from './pages/ProjectDetailPage'
import DocumentUploadPage from './pages/DocumentUploadPage'
import MentorSelectionPage from './pages/MentorSelectionPage'
import MentorFeedbackChatPage from './pages/MentorFeedbackChatPage'
import ReviewBoardPrototype from './pages/board/ReviewBoardPrototype'
// 용준/Claude(2026-07-20): 개발용 아이디어 발전 회의 프리뷰 화면 — 기존 심사 화면/라우팅과
// 무관한 별도 경로. backend가 ENABLE_IDEATION_PREVIEW=false면 API가 404를 주지만, 화면
// 자체는 항상 접근 가능하다(에러 메시지로 비활성화 여부를 확인하게 된다).
import IdeationPreviewPage from './pages/IdeationPreviewPage'

function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/mypage" element={<MyPage />} />
      <Route path="/projects" element={<ProjectListPage />} />
      <Route path="/projects/new" element={<DocumentUploadPage />} />
      <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
      <Route path="/projects/:projectId/analysis" element={<MentorSelectionPage />} />
      <Route path="/projects/:projectId/feedback-chat" element={<MentorFeedbackChatPage />} />
      {/* 가은/Claude(2026-07-20): 서비스 방향 전환 프로토타입 — "작성 후" 경로는 실제 API에
          연결됨, "작성 전"은 아직 더미(아래 /ideation-preview가 실제 아이디어 발전 회의
          API — 다음 작업에서 이 프로토타입과 연결 예정). 기존 /projects 플로우는 legacy로
          그대로 둔다. */}
      <Route path="/board" element={<ReviewBoardPrototype />} />
      <Route path="/ideation-preview" element={<IdeationPreviewPage />} />
    </Routes>
  )
}

export default App
