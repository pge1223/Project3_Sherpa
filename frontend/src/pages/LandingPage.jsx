import { useNavigate } from 'react-router-dom'
import './LandingPage.css'

const TAGLINE_WORDS = '어떤 공모전을 준비해볼까요?'.split(' ')
const WORD_START_DELAY = 0.9
const WORD_STEP = 0.18

// 새벽 하늘 영역(상단)에만 뿌리는 별 — 위치·반짝임 딜레이 고정값
const STARS = [
  { left: '8%', top: '12%', delay: '0s' },
  { left: '19%', top: '34%', delay: '1.1s' },
  { left: '31%', top: '8%', delay: '0.6s' },
  { left: '47%', top: '22%', delay: '1.7s' },
  { left: '62%', top: '6%', delay: '0.3s' },
  { left: '74%', top: '28%', delay: '2.2s' },
  { left: '88%', top: '14%', delay: '0.9s' },
  { left: '93%', top: '38%', delay: '1.4s' },
]

export default function LandingPage() {
  const navigate = useNavigate()

  return (
    <div className="landing-page">
      <div className="landing-stars" aria-hidden="true">
        {STARS.map((s, i) => (
          <i key={i} style={{ left: s.left, top: s.top, animationDelay: s.delay }} />
        ))}
      </div>

      <div className="landing-content">
        <img src="/images/logo1.png" alt="AI Review Board" className="landing-logo" />

        <p className="landing-tagline">
          {TAGLINE_WORDS.map((word, i) => (
            <span key={i} className="landing-word" style={{ animationDelay: `${WORD_START_DELAY + i * WORD_STEP}s` }}>
              {word}
            </span>
          ))}
        </p>

        <p className="landing-sub">
          공모전 분석부터 문서 피드백까지, AI 멘토가 당신과 함께 합니다.
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
