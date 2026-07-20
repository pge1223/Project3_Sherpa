import { Routes, Route } from 'react-router-dom'
import LandingPage from './pages/LandingPage'
import LoginPage from './pages/LoginPage'
import ProjectListPage from './pages/ProjectListPage'
import ProjectDetailPage from './pages/ProjectDetailPage'
import DocumentUploadPage from './pages/DocumentUploadPage'
import MentorSelectionPage from './pages/MentorSelectionPage'
import MentorFeedbackChatPage from './pages/MentorFeedbackChatPage'
import ReviewBoardPrototype from './pages/board/ReviewBoardPrototype'

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
      {/* 가은/Claude(2026-07-20): 서비스 방향 전환 프로토타입 — 더미 데이터,
          백엔드 미연결. 기존 /projects 플로우는 legacy로 그대로 둔다. */}
      <Route path="/board" element={<ReviewBoardPrototype />} />
    </Routes>
  )
}

export default App
