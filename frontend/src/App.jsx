import { Routes, Route } from 'react-router-dom'
import LandingPage from './pages/LandingPage'
import LoginPage from './pages/LoginPage'
import ProjectListPage from './pages/ProjectListPage'
import ProjectDetailPage from './pages/ProjectDetailPage'
import DocumentUploadPage from './pages/DocumentUploadPage'
import MentorSelectionPage from './pages/MentorSelectionPage'
import MentorFeedbackChatPage from './pages/MentorFeedbackChatPage'

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
    </Routes>
  )
}

export default App
