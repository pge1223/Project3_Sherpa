import { Routes, Route } from 'react-router-dom'
import LandingPage from './pages/LandingPage'
import LoginPage from './pages/LoginPage'
import ProjectListPage from './pages/ProjectListPage'
import ProjectDetailPage from './pages/ProjectDetailPage'
import DocumentUploadPage from './pages/DocumentUploadPage'
import MentorSelectionPage from './pages/MentorSelectionPage'
import MentorFeedbackChatPage from './pages/MentorFeedbackChatPage'
// 용준/Claude(2026-07-20): 개발용 아이디어 발전 회의 프리뷰 화면 — 기존 심사 화면/라우팅과
// 무관한 별도 경로. backend가 ENABLE_IDEATION_PREVIEW=false면 API가 404를 주지만, 화면
// 자체는 항상 접근 가능하다(에러 메시지로 비활성화 여부를 확인하게 된다).
import IdeationPreviewPage from './pages/IdeationPreviewPage'
// 용준/Claude(2026-07-20): 개발용 "대화형 아이디어 발전 회의" 프리뷰 화면 — 배치형
// IdeationPreviewPage와 별개의 화면/경로다. backend가 ENABLE_IDEATION_PREVIEW=false면
// API가 404를 준다(화면 자체는 항상 접근 가능).
import IdeationConversationPreviewPage from './pages/IdeationConversationPreviewPage'

function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/projects" element={<ProjectListPage />} />
      <Route path="/projects/new" element={<DocumentUploadPage />} />
      <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
      <Route path="/projects/:projectId/analysis" element={<MentorSelectionPage />} />
      <Route path="/projects/:projectId/feedback-chat" element={<MentorFeedbackChatPage />} />
      <Route path="/ideation-preview" element={<IdeationPreviewPage />} />
      <Route path="/ideation-conversation-preview" element={<IdeationConversationPreviewPage />} />
    </Routes>
  )
}

export default App
