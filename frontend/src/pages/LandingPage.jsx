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

        {/* 가은/Claude(2026-07-21): "내 프로젝트"가 실제로 사용자별로 구분되려면
            로그인을 거쳐야 한다 — /board로 바로 보내면 인증 헤더가 없어 백엔드가
            전부 guest@local 하나로 묶어버린다(get_current_user() 게스트 폴백).
            로그인 화면을 다시 거치도록 되돌린다. */}
        <button className="landing-cta" onClick={() => navigate('/login')}>
          시작하기
        </button>
      </div>
    </div>
  )
}
