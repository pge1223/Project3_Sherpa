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
            다만 "한 번 로그인하면 그다음부턴 자동 로그인"을 원해서, 이미
            localStorage에 토큰이 있으면(그 컴퓨터에서 로그인한 적 있으면) 로그인
            화면을 또 거치지 않고 바로 board로 보낸다. */}
        <button
          className="landing-cta"
          onClick={() => navigate(localStorage.getItem('auth_token') ? '/board' : '/login')}
        >
          시작하기
        </button>
      </div>
    </div>
  )
}
