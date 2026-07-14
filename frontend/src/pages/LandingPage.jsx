import { useNavigate } from 'react-router-dom'
import SpaceBackground from '../components/landing/SpaceBackground'
import './LandingPage.css'

const TAGLINE_WORDS = 'AI 심사위원단에게 당신의 사업계획서를 검토받아보세요'.split(' ')
const WORD_START_DELAY = 0.9
const WORD_STEP = 0.18

export default function LandingPage() {
  const navigate = useNavigate()

  return (
    <div className="landing-page">
      <SpaceBackground />

      <div className="landing-content">
        <img src="/images/logo4.png" alt="AI Review Board" className="landing-logo" />

        <p className="landing-tagline">
          {TAGLINE_WORDS.map((word, i) => (
            <span key={i} className="landing-word" style={{ animationDelay: `${WORD_START_DELAY + i * WORD_STEP}s` }}>
              {word}
            </span>
          ))}
        </p>

        <button className="landing-cta" onClick={() => navigate('/login')}>
          시작하기
        </button>
      </div>
    </div>
  )
}
