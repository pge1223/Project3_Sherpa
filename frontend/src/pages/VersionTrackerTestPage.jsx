// 작성자: 경이 (테스트 전용 — 별도 섹션. 가은님 새 디자인/board 프로토타입은 건드리지 않음)
// 목적: "1회성 답변이 아닌 버전 추적형 User RAG = 개인 맞춤형 피드백 루프"를 프론트에서 먼저
//   눈으로 검증하는 실험 화면. 도메인은 IT(기술 기반) 공모전, 심사위원은 기획 위원 + 개발
//   위원 2인. v1.0만 먼저 보이고 "다음 수정본 제출"로 v1.1 -> v1.2 -> v1.3 을 하나씩 쌓아가며,
//   위원 탭으로 각 위원의 점수·피드백만 골라 보고, 항목별 이전 vs 현재 막대 비교로 점수
//   상승세와 해결 과정을 한눈에 본다.
//   ★ 디자인: 가은님의 새 웜 화이트/글래스 톤(ReviewBoardPrototype .rb-root)에 맞춘
//   VersionTrackerTest.css(.vt-root)를 그대로 쓴다 — /board 플로우에 이어붙이기 쉽게.
//   ★ 실데이터 매핑: 각 버전의 위원별 피드백 = review_output.reviewer_results,
//   버전 간 점수 증감·해결/잔존/신규 = ai/meeting/scoring/comparison.py 의
//   build_revision_comparison() 출력. 둘 다 내 백엔드 산출물이라 mock -> 실데이터 교체만 하면 됨.
// import: react, react-router-dom, lucide-react(가은 새 디자인과 동일 아이콘), 스타일 CSS.

import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ArrowLeft, TrendingUp, TrendingDown, CheckCircle2, AlertCircle, Plus,
  Lightbulb, Compass, Cpu, FlaskConical,
  GitBranch, GraduationCap, FileText, AlertTriangle, Zap, ChevronDown,
} from 'lucide-react'
import './VersionTrackerTest.css'

const CRITERION_MAX = 25 // 4항목 × 25 = 100점

// --- 개인화 입력: 제출 프로필 (TEST 2종) -----------------------------------
// "버전 추적형 User RAG = 개인 맞춤형 피드백 루프"를 살리기 위해, 수정본 제출(기본)에 더해
// GitHub·이력/교육수준을 함께 제출한다. 개발 위원 피드백은 이 프로필에 따라 구현 난이도와
// 설명 상세도를 다르게 보여준다.
const PROFILES = {
  nonmajor: {
    key: 'nonmajor',
    label: '비전공자',
    difficulty: 'hard',
    education: '경영학 학사 졸업',
    github: 'github.com/user · 커밋 32, HTML/CSS 위주 (백엔드 이력 없음)',
    experience: '공모전·IT 인턴 경험 없음',
  },
  major: {
    key: 'major',
    label: '컴퓨터공학 전공자',
    difficulty: 'easy',
    education: '컴퓨터공학 학사 졸업',
    github: 'github.com/user · 커밋 480, Python·FastAPI·React, RAG 토이프로젝트 2건',
    experience: 'IT 스타트업 백엔드 인턴 6개월 · 교내 해커톤 수상 1회',
  },
}

const DIFFICULTY = {
  hard: { label: '구현 난이도 · 어려울 수 있음', color: '#e0603d', bg: 'rgba(224,96,61,0.1)', Icon: AlertTriangle },
  easy: { label: '구현 난이도 · 쉬움', color: '#16a37a', bg: 'rgba(22,163,122,0.1)', Icon: Zap },
}

// 개발 위원 지적(미해결/신규)에 대한 구현 가이드. profile별로 상세도가 다르다.
// nonmajor = 길고 친절한 단계별(자세히 보기), major = 짧고 간결한 한 줄.
const IMPL_GUIDE = {
  'f-stack': {
    nonmajor: '모델·DB 선택은 비전공자에게 가장 막막한 부분이에요. ① 임베딩은 한국어에 강한 KURE-v1을 그대로 쓰세요(직접 학습 X, HuggingFace에서 이름만 지정). ② 벡터DB는 설치가 쉬운 Chroma를 로컬 폴더에 저장(persistent)하도록 한 줄 설정. ③ "top-k=5"는 "질문과 가장 비슷한 문단 5개를 가져온다"는 뜻이니 5로 두면 됩니다. ④ LLM은 요약엔 저렴한 모델, 최종 답변엔 좋은 모델로 나누면 비용이 절반 이하로 줄어요. 각 단계는 공식 문서 예제 코드를 복사해 이름만 바꾸면 동작합니다.',
    major: 'KURE-v1 + Chroma(persistent, top-k=5) + LLM 2티어 라우팅. 3장 다이어그램에 스택·파라미터만 표기하면 됩니다.',
  },
  'f-eval': {
    nonmajor: '"검색이 잘 되는지"를 숫자로 보여주는 부분이에요. ① 정답이 있는 질문 30개를 미리 만드세요(질문 ↔ 답이 나와야 하는 문단). ② 시스템이 가져온 문단 5개 안에 정답 문단이 있으면 성공 → 30개 중 성공 개수가 "Recall@5"입니다(예: 27/30=0.9). ③ 답변이 그 근거를 실제로 인용했는지는 몇 개만 눈으로 확인하면 됩니다. 엑셀 표 하나로도 충분해요.',
    major: '골든셋 30건으로 Recall@5·근거 인용 정확도만 4장에 표로. pytest 파라미터라이즈로 자동화하면 30분.',
  },
  'a-parse': {
    nonmajor: '업로드한 파일에서 글자를 뽑아 잘게 나누는 과정이에요. ① PyMuPDF는 PDF에서 텍스트를 뽑는 무료 라이브러리로 예제 5줄이면 됩니다. ② "청킹"은 긴 글을 800토큰(대략 한글 1,000자)씩 자르는 것, "overlap 100"은 자를 때 앞뒤를 조금 겹쳐 문맥이 끊기지 않게 하는 안전장치예요. ③ 각 조각에 "몇 쪽에서 왔는지"만 같이 저장하면 나중에 출처를 보여줄 수 있어요. 도식은 네모 4개(파일→텍스트→조각→저장)를 화살표로 이으면 됩니다.',
    major: 'PyMuPDF → RecursiveCharacterTextSplitter(800/100) → page 메타 보존. 3장에 4-스텝 다이어그램만.',
  },
  'a-privacy': {
    nonmajor: '개인정보를 안전하게 다루는 규칙을 적는 부분이에요(코딩보다 정책 서술에 가깝습니다). ① 파일을 어디에 저장하는지, ② 저장 시 암호화 옵션을 켜는지, ③ 며칠 뒤 자동 삭제하는지(예: 30일), ④ "AI 학습에는 절대 사용하지 않음"을 5장에 문장으로 명시하면 됩니다. 기술 구현은 클라우드 설정 몇 개면 되고, 핵심은 "문서에 약속을 적는 것"이에요.',
    major: '저장 시 암호화(KMS)·TTL 30일·학습 배제 조항. 인프라 설정 + 5장 정책 문구. 반나절.',
  },
  'f-scale': {
    nonmajor: '"사람이 몰리면 돈이 얼마나 드나"를 추정하는 부분이에요. ① 동시에 몇 명이 쓸지 가정(예: 최대 20명), ② 회의 1건에 토큰이 대략 얼마 드는지 API 가격표로 계산(예: 회의 1건 ≈ 100원), ③ 같은 문서를 또 물으면 캐시로 재사용해 비용을 아끼는 전략만 한 단락 적으면 됩니다. 실제 부하 테스트까진 필요 없고 표 하나면 충분해요.',
    major: '동시요청 가정 → 월 토큰·비용 산정표 + 응답 캐싱/요청 큐잉 한 단락. 6장에 추정치로.',
  },
  'a-fallback': {
    nonmajor: 'AI나 외부 서비스가 잠깐 죽었을 때 앱이 멈추지 않게 하는 안전장치예요. ① 응답이 너무 늦으면 몇 초 후 포기(타임아웃), ② 실패하면 한두 번 다시 시도(재시도), ③ 좋은 모델이 안 되면 저렴한 모델로 대신(폴백), ④ 그래도 안 되면 "잠시 후 다시 시도해주세요" 안내. 이 4가지를 순서도로 3장에 그리면 되고, 대부분 라이브러리 옵션으로 처리돼요.',
    major: 'timeout → retry(backoff) → 모델 폴백(고성능→경량) → user-facing 에러. 3장에 시퀀스만. tenacity로 구현.',
  },
}

const COMMITTEES = {
  planning: { name: '기획 위원', Icon: Compass, color: '#7c5cea', dim: 'rgba(124,92,234,0.12)', desc: '문제 정의 · 사용자 가치 · 차별성' },
  dev: { name: '개발 위원', Icon: Cpu, color: '#e0603d', dim: 'rgba(224,96,61,0.12)', desc: '기술 구현 · 아키텍처 · 데이터' },
}

const JUDGMENT_LABEL = {
  strong: { text: '우수', color: '#16a37a', bg: 'rgba(22,163,122,0.12)' },
  acceptable: { text: '적정', color: '#7c5cea', bg: 'rgba(124,92,234,0.12)' },
  needs_improvement: { text: '보완 필요', color: '#b8830b', bg: 'rgba(184,131,11,0.14)' },
  critical_risk: { text: '중대 리스크', color: '#e0603d', bg: 'rgba(224,96,61,0.12)' },
}

const STATUS_META = {
  open: { Icon: AlertCircle, label: '보완 필요', color: '#b8830b', bg: 'rgba(184,131,11,0.09)', border: 'rgba(184,131,11,0.26)' },
  new: { Icon: Plus, label: '신규 지적', color: '#e0603d', bg: 'rgba(224,96,61,0.08)', border: 'rgba(224,96,61,0.24)' },
  resolved: { Icon: CheckCircle2, label: '해결됨', color: '#16a37a', bg: 'rgba(22,163,122,0.08)', border: 'rgba(22,163,122,0.24)' },
}

// --- Mock 데이터 (버전 추적 스토리: 50 -> 72 -> 86 -> 95) ------------------
const ALL_VERSIONS = [
  {
    version: 'v1.0', label: '최초 제출', submitted_at: '2026-07-15 14:20', total_score: 50,
    criteria: [
      {
        id: 'problem', name: '문제 정의 · 차별성', committee: 'planning', score: 14, judgment: 'needs_improvement',
        feedback: [
          { id: 'p-persona', status: 'open', text: '타깃 사용자가 "예비창업 대학생"인지 "일반 소상공인"인지 문서 전반에서 혼재됩니다.', suggestion: '1장 도입부에 페르소나 1명(예: 예비창업 대학생 김OO, 25세)으로 좁혀 정의하고, 그 사용자의 핵심 문제를 한 문장으로 제시하세요.' },
          { id: 'p-diff', status: 'open', text: '경쟁 서비스 대비 차별점이 "더 똑똑함" 수준의 정성적 서술뿐입니다.', suggestion: '기능 4개 × 경쟁사 2곳 비교표를 넣어 정량적 차별점(무엇이 얼마나 다른지)을 보이세요.' },
        ],
      },
      {
        id: 'impact', name: '기대효과 · 사용자 가치', committee: 'planning', score: 12, judgment: 'needs_improvement',
        feedback: [
          { id: 'i-metric', status: 'open', text: '기대효과가 "효율 향상" 같은 추상적 표현에 그칩니다.', suggestion: '"피드백 1회 소요 3시간 → 20분", "재수정률 30% 감소"처럼 측정 가능한 지표 2개로 바꾸세요.' },
        ],
      },
      {
        id: 'feasibility', name: '기술 실현 가능성', committee: 'dev', score: 13, judgment: 'critical_risk',
        feedback: [
          { id: 'f-stack', status: 'open', text: '사용할 LLM · 임베딩 모델 · 벡터DB가 특정되어 있지 않습니다.', suggestion: '3장 아키텍처에 "임베딩=KURE-v1, 벡터DB=Chroma(persistent), 검색 top-k=5, LLM=경량/고성능 2단계 분리"처럼 스택과 파라미터를 명시하세요.' },
          { id: 'f-eval', status: 'open', text: 'RAG 검색 정확도를 어떻게 검증할지 계획이 없습니다.', suggestion: '평가셋 30건 + Recall@5 · 근거 인용 정확도 지표로 측정하는 검증 절차를 4장에 추가하세요.' },
        ],
      },
      {
        id: 'architecture', name: '아키텍처 · 데이터 처리', committee: 'dev', score: 11, judgment: 'critical_risk',
        feedback: [
          { id: 'a-parse', status: 'open', text: '업로드 문서(PDF/DOCX/PPT)의 파싱 · 청킹 전략이 빠져 있습니다.', suggestion: '"PyMuPDF 파싱 → 800토큰/overlap 100 청킹 → 출처 페이지 메타 보존" 파이프라인을 도식으로 3장에 넣으세요.' },
          { id: 'a-privacy', status: 'open', text: '사업계획서 내 민감정보 처리 방침이 없습니다.', suggestion: '저장 위치 · 암호화 · 보관기간(예: 30일)과 "모델 학습 미사용"을 5장 보안 절에 명시하세요.' },
        ],
      },
    ],
  },
  {
    version: 'v1.1', label: '1차 수정본', submitted_at: '2026-07-18 10:15', total_score: 72,
    criteria: [
      {
        id: 'problem', name: '문제 정의 · 차별성', committee: 'planning', score: 20, judgment: 'acceptable',
        feedback: [
          { id: 'p-persona', status: 'resolved', text: '타깃 사용자 혼재', note: '1장에 페르소나(예비창업 대학생 김OO, 25세)로 좁히고 핵심 문제를 한 문장으로 제시함.' },
          { id: 'p-diff', status: 'resolved', text: '차별점이 정성적', note: '경쟁사 2곳 × 기능 4개 비교표를 2장에 추가함.' },
        ],
      },
      {
        id: 'impact', name: '기대효과 · 사용자 가치', committee: 'planning', score: 17, judgment: 'acceptable',
        feedback: [
          { id: 'i-metric', status: 'resolved', text: '기대효과가 추상적', note: '"소요 3시간→20분", "재수정률 30%↓" 정량 지표로 교체함.' },
          { id: 'i-evidence', status: 'new', text: '제시한 지표의 근거(측정 방법 · 표본)가 없어 신뢰도가 낮습니다.', suggestion: '파일럿 5명 대상 사전측정값을 각주로 붙여 지표의 출처를 밝히세요.' },
        ],
      },
      {
        id: 'feasibility', name: '기술 실현 가능성', committee: 'dev', score: 19, judgment: 'acceptable',
        feedback: [
          { id: 'f-stack', status: 'resolved', text: '모델 · 벡터DB 미명시', note: '3장에 KURE-v1 + Chroma(top-k=5), LLM 2단계 분리를 명시함.' },
          { id: 'f-eval', status: 'open', text: 'RAG 검색 정확도 검증 절차가 아직 없습니다.', suggestion: '평가셋 30건 + Recall@5 · 근거 인용 정확도 지표로 4장에 검증 절차를 추가하세요.' },
        ],
      },
      {
        id: 'architecture', name: '아키텍처 · 데이터 처리', committee: 'dev', score: 16, judgment: 'needs_improvement',
        feedback: [
          { id: 'a-parse', status: 'resolved', text: '파싱 · 청킹 전략 부재', note: 'PyMuPDF 파싱 → 800토큰/overlap 100 청킹 파이프라인 도식을 3장에 추가함.' },
          { id: 'a-privacy', status: 'open', text: '민감정보 처리 방침이 아직 없습니다.', suggestion: '저장 암호화 · 보관 30일 · 학습 미사용을 5장 보안 절에 명시하세요.' },
        ],
      },
    ],
  },
  {
    version: 'v1.2', label: '2차 수정본', submitted_at: '2026-07-21 09:40', total_score: 86,
    criteria: [
      { id: 'problem', name: '문제 정의 · 차별성', committee: 'planning', score: 23, judgment: 'strong', feedback: [] },
      {
        id: 'impact', name: '기대효과 · 사용자 가치', committee: 'planning', score: 21, judgment: 'strong',
        feedback: [
          { id: 'i-evidence', status: 'resolved', text: '지표 근거 부재', note: '파일럿 5명 사전측정값을 각주로 추가해 지표 신뢰도를 확보함.' },
        ],
      },
      {
        id: 'feasibility', name: '기술 실현 가능성', committee: 'dev', score: 22, judgment: 'strong',
        feedback: [
          { id: 'f-eval', status: 'resolved', text: 'RAG 검증 절차 부재', note: '평가셋 30건 + Recall@5 · 근거 인용 정확도 검증 절차를 4장에 추가함.' },
          { id: 'f-scale', status: 'new', text: '동시 사용자 부하와 LLM 호출 비용 추정이 없습니다.', suggestion: '예상 동시요청 수 기준 월 토큰 사용량 · 비용과 캐싱/큐잉 전략을 6장에 추정치로 넣으세요.' },
        ],
      },
      {
        id: 'architecture', name: '아키텍처 · 데이터 처리', committee: 'dev', score: 20, judgment: 'strong',
        feedback: [
          { id: 'a-privacy', status: 'resolved', text: '민감정보 처리 방침 부재', note: '5장에 저장 암호화 · 보관 30일 · 학습 미사용을 명시함.' },
          { id: 'a-fallback', status: 'new', text: 'LLM · 외부 API 장애 시 폴백 전략이 없습니다.', suggestion: '타임아웃 · 재시도 · 모델 폴백(고성능→경량) 순서와 실패 시 사용자 안내를 3장 아키텍처에 추가하세요.' },
        ],
      },
    ],
  },
  {
    version: 'v1.3', label: '3차 수정본', submitted_at: '2026-07-24 16:05', total_score: 95,
    criteria: [
      { id: 'problem', name: '문제 정의 · 차별성', committee: 'planning', score: 24, judgment: 'strong', feedback: [] },
      { id: 'impact', name: '기대효과 · 사용자 가치', committee: 'planning', score: 23, judgment: 'strong', feedback: [] },
      {
        id: 'feasibility', name: '기술 실현 가능성', committee: 'dev', score: 24, judgment: 'strong',
        feedback: [
          { id: 'f-scale', status: 'resolved', text: '부하 · 비용 추정 부재', note: '6장에 월 토큰 사용량 · 비용과 캐싱/큐잉 전략을 추정치로 추가함.' },
        ],
      },
      {
        id: 'architecture', name: '아키텍처 · 데이터 처리', committee: 'dev', score: 24, judgment: 'strong',
        feedback: [
          { id: 'a-fallback', status: 'resolved', text: '장애 폴백 전략 부재', note: '3장에 타임아웃 · 재시도 · 모델 폴백 순서와 사용자 안내를 추가함.' },
        ],
      },
    ],
  },
]

// --- 유틸 ------------------------------------------------------------------
function criterionBefore(versions, versionIndex, criterionId) {
  if (versionIndex === 0) return null
  const prev = versions[versionIndex - 1].criteria.find((c) => c.id === criterionId)
  return prev ? prev.score : null
}
function committeeScore(version, committee) {
  return version.criteria.filter((c) => c.committee === committee).reduce((s, c) => s + c.score, 0)
}

function useCountUp(target, duration = 850) {
  const [val, setVal] = useState(target)
  const fromRef = useRef(target)
  useEffect(() => {
    const from = fromRef.current
    if (from === target) return
    const start = performance.now()
    let raf
    const tick = (now) => {
      const p = Math.min(1, (now - start) / duration)
      const eased = 1 - Math.pow(1 - p, 3)
      setVal(Math.round(from + (target - from) * eased))
      if (p < 1) raf = requestAnimationFrame(tick)
      else fromRef.current = target
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [target, duration])
  return val
}
function CountUp({ value, className, style }) {
  return <span className={className} style={style}>{useCountUp(value)}</span>
}

// --- 표시 컴포넌트 ---------------------------------------------------------
function DeltaPill({ value, size = 'md' }) {
  const up = value > 0
  const flat = value === 0
  const color = flat ? '#918d9f' : up ? '#16a37a' : '#e0603d'
  const bg = flat ? 'rgba(145,141,159,0.12)' : up ? 'rgba(22,163,122,0.12)' : 'rgba(224,96,61,0.12)'
  const Icon = up ? TrendingUp : TrendingDown
  const pad = size === 'lg' ? '6px 14px' : '3px 9px'
  const fs = size === 'lg' ? 15 : 12
  return (
    <span className="mono" style={{ display: 'inline-flex', alignItems: 'center', gap: 5, borderRadius: 99, fontWeight: 700, whiteSpace: 'nowrap', color, background: bg, padding: pad, fontSize: fs }}>
      {!flat && <Icon size={size === 'lg' ? 15 : 12} />}
      {flat ? '±0' : `${up ? '+' : ''}${value}점`}
    </span>
  )
}

function JudgmentChange({ before, after }) {
  const a = JUDGMENT_LABEL[after]
  const b = JUDGMENT_LABEL[before]
  if (!a) return null
  const changed = before && before !== after
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      {changed && b && (
        <>
          <span style={{ ...chip, color: b.color, background: b.bg, opacity: 0.5 }}>{b.text}</span>
          <span style={{ color: '#c7c3d0', fontSize: 12 }}>→</span>
        </>
      )}
      <span style={{ ...chip, color: a.color, background: a.bg }}>{a.text}</span>
    </span>
  )
}
const chip = { fontSize: 11.5, fontWeight: 700, padding: '3px 10px', borderRadius: 8 }

// 이전 vs 현재 막대 비교 (핵심 시각화).
function CompareBars({ before, after, max, animKey }) {
  const rows = before == null
    ? [{ label: '출발점', value: after, fill: 'linear-gradient(90deg,#9b82f0,#7c5cea)', strong: true, delay: 0 }]
    : [
        { label: '이전', value: before, fill: '#d8cff0', strong: false, delay: 0 },
        { label: '현재', value: after, fill: 'linear-gradient(90deg,#9b82f0,#7c5cea)', strong: true, delay: 0.15 },
      ]
  return (
    <div key={animKey} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {rows.map((r) => (
        <div key={r.label} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span className="mono" style={{ fontSize: 11, width: 40, flexShrink: 0, color: r.strong ? '#5b5770' : '#918d9f', fontWeight: r.strong ? 700 : 500 }}>{r.label}</span>
          <div style={{ flex: 1, height: 14, borderRadius: 999, background: 'var(--bg-2)', overflow: 'hidden', minWidth: 120 }}>
            <div className="vt-bar-seg" style={{ height: '100%', width: `${(r.value / max) * 100}%`, background: r.fill, animationDelay: `${r.delay}s` }} />
          </div>
          <span className="mono" style={{ fontWeight: 800, width: 24, textAlign: 'right', flexShrink: 0, color: r.strong ? '#7c5cea' : '#918d9f', fontSize: r.strong ? 17 : 14 }}>{r.value}</span>
          <span className="mono" style={{ fontSize: 11, color: '#b6b1c2', width: 24, flexShrink: 0 }}>/{max}</span>
        </div>
      ))}
    </div>
  )
}

function FeedbackItem({ f, guide }) {
  const [open, setOpen] = useState(false)
  const s = STATUS_META[f.status]
  const Icon = s.Icon
  // guide: { level, detail, nonMajor } — 개발 위원의 미해결/신규 지적에만 주어진다.
  const diff = guide ? DIFFICULTY[guide.level] : null
  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, padding: '11px 13px', borderRadius: 11, background: s.bg, border: `1px solid ${s.border}` }}>
      <span style={{ flexShrink: 0, width: 20, height: 20, borderRadius: '50%', background: s.color, color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', marginTop: 1 }}>
        <Icon size={12} strokeWidth={3} />
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 7, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 11.5, fontWeight: 800, flexShrink: 0, color: s.color }}>{s.label}</span>
          <span style={{ fontSize: 13.5, lineHeight: 1.5, fontWeight: 600, textDecoration: f.status === 'resolved' ? 'line-through' : 'none', color: f.status === 'resolved' ? '#a8a4b2' : '#3a3750' }}>{f.text}</span>
        </div>
        {f.suggestion && (
          <div style={{ display: 'flex', gap: 7, marginTop: 8, fontSize: 13, lineHeight: 1.6, color: '#5b5770', background: 'rgba(255,255,255,0.6)', padding: '8px 11px', borderRadius: 9 }}>
            <Lightbulb size={15} color="#b8830b" style={{ flexShrink: 0, marginTop: 1 }} />
            <span><b style={{ color: '#3a3750' }}>이렇게 고치세요:</b> {f.suggestion}</span>
          </div>
        )}

        {/* 개인화: 개발 위원 구현 난이도 (프로필 기반) */}
        {guide && diff && (
          <div style={{ marginTop: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <span className="mono" style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11.5, fontWeight: 700, padding: '4px 10px', borderRadius: 99, color: diff.color, background: diff.bg }}>
                <diff.Icon size={12} /> {diff.label}
              </span>
              {guide.nonMajor && (
                <button className="vt-tab" onClick={() => setOpen((v) => !v)}
                  style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, fontWeight: 700, color: '#7c5cea', background: 'transparent', border: 'none', cursor: 'pointer', padding: '2px 4px' }}>
                  자세히 보기 <ChevronDown size={13} style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.18s ease' }} />
                </button>
              )}
            </div>
            {guide.nonMajor ? (
              open && (
                <div style={{ marginTop: 8, fontSize: 12.5, lineHeight: 1.75, color: '#4a4660', background: 'rgba(224,96,61,0.06)', border: '1px solid rgba(224,96,61,0.16)', padding: '11px 13px', borderRadius: 10 }}>
                  {guide.detail}
                </div>
              )
            ) : (
              <div style={{ marginTop: 7, fontSize: 12.5, lineHeight: 1.6, color: '#5b5770' }}>{guide.detail}</div>
            )}
          </div>
        )}

        {f.note && (
          <div style={{ display: 'flex', gap: 7, marginTop: 8, fontSize: 13, lineHeight: 1.6, color: '#12876a' }}>
            <CheckCircle2 size={15} style={{ flexShrink: 0, marginTop: 1 }} />
            <span><b>반영됨:</b> {f.note}</span>
          </div>
        )}
      </div>
    </div>
  )
}

function CriterionCard({ c, before, index, animKey, isDev, profile }) {
  const delta = before == null ? null : c.score - before
  // 개발 위원의 미해결/신규 지적에만 구현 난이도 가이드를 붙인다(프로필 기반).
  const guideFor = (f) => {
    if (!isDev || (f.status !== 'open' && f.status !== 'new')) return null
    const g = IMPL_GUIDE[f.id]
    if (!g) return null
    return { level: profile.difficulty, detail: g[profile.key], nonMajor: profile.key === 'nonmajor' }
  }
  return (
    <div className="vt-fade card glass" style={{ animationDelay: `${index * 90}ms` }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 14, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 15.5, fontWeight: 700 }}>{c.name}</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          {delta != null && <DeltaPill value={delta} />}
          <JudgmentChange before={null} after={c.judgment} />
        </div>
      </div>

      <CompareBars before={before} after={c.score} max={CRITERION_MAX} animKey={animKey} />

      {c.feedback.length > 0 ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 14 }}>
          {c.feedback.map((f) => <FeedbackItem key={f.id} f={f} guide={guideFor(f)} />)}
        </div>
      ) : (
        <div style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 13, color: '#16a37a', marginTop: 14, background: 'rgba(22,163,122,0.08)', padding: '10px 13px', borderRadius: 10, fontWeight: 600 }}>
          <CheckCircle2 size={15} /> 남은 지적 없음 — 이 항목은 깔끔합니다
        </div>
      )}
    </div>
  )
}

// 버전별 총점 라인 차트(SVG).
function ScoreTrendChart({ versions, selectedIndex, onSelect }) {
  const W = 640, H = 220, padX = 46, padTop = 50, padBottom = 44
  const innerW = W - padX * 2
  const innerH = H - padTop - padBottom
  const scores = versions.map((v) => v.total_score)
  const yMin = Math.max(0, Math.min(...scores) - 12)
  const yMax = Math.min(100, Math.max(...scores) + 10)
  const n = versions.length
  const xOf = (i) => (n === 1 ? W / 2 : padX + (innerW * i) / (n - 1))
  const yOf = (s) => padTop + innerH * (1 - (s - yMin) / (yMax - yMin || 1))
  const pts = versions.map((v, i) => ({ x: xOf(i), y: yOf(v.total_score), v, i }))
  const linePath = pts.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ')
  const baseY = H - padBottom
  const areaPath = `${linePath} L ${pts[pts.length - 1].x.toFixed(1)} ${baseY} L ${pts[0].x.toFixed(1)} ${baseY} Z`

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: 'block' }} key={n}>
      <defs>
        <linearGradient id="vtArea" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#7c5cea" stopOpacity="0.24" />
          <stop offset="100%" stopColor="#7c5cea" stopOpacity="0" />
        </linearGradient>
      </defs>
      <line x1={padX} y1={baseY} x2={W - padX} y2={baseY} stroke="rgba(28,26,46,0.08)" strokeWidth="1" />
      {n > 1 && <path className="vt-area" d={areaPath} fill="url(#vtArea)" />}
      {n > 1 && <path className="vt-line" pathLength="1" d={linePath} fill="none" stroke="#7c5cea" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />}
      {pts.slice(1).map((p, i) => {
        const prev = pts[i]
        const d = p.v.total_score - prev.v.total_score
        const mx = (prev.x + p.x) / 2
        const my = (prev.y + p.y) / 2 - 13
        return (
          <text key={`d-${p.v.version}`} className="vt-dot-label mono" x={mx} y={my} textAnchor="middle" style={{ animationDelay: '0.9s' }} fontSize="12.5" fontWeight="800" fill={d >= 0 ? '#16a37a' : '#e0603d'}>
            {d >= 0 ? '+' : ''}{d}
          </text>
        )
      })}
      {pts.map((p, i) => {
        const active = i === selectedIndex
        return (
          <g key={p.v.version} className="vt-dotg" onClick={() => onSelect(i)}>
            <circle cx={p.x} cy={p.y} r="20" fill="transparent" />
            <circle className="vt-dot" cx={p.x} cy={p.y} r={active ? 8 : 5.5} fill={active ? '#7c5cea' : '#faf8f4'} stroke="#7c5cea" strokeWidth="3" style={{ animationDelay: `${0.4 + i * 0.12}s` }} />
            <text className="vt-dot-label mono" x={p.x} y={p.y - 17} textAnchor="middle" style={{ animationDelay: `${0.5 + i * 0.12}s` }} fontSize="14" fontWeight="800" fill="#1c1a2e">{p.v.total_score}</text>
            <text className="vt-dot-label mono" x={p.x} y={baseY + 21} textAnchor="middle" style={{ animationDelay: `${0.5 + i * 0.12}s` }} fontSize="11.5" fontWeight={active ? 800 : 600} fill={active ? '#7c5cea' : '#918d9f'}>{p.v.version}</text>
          </g>
        )
      })}
    </svg>
  )
}

// 제출 정보(개인화 입력) + TEST 프로필 토글.
function SubmissionCard({ profileKey, onChange }) {
  const p = PROFILES[profileKey]
  const rows = [
    { Icon: FileText, label: '수정본 (기본)', value: '문서 재제출 — 버전 추적의 기본 입력', tag: '필수', tagCls: 'green' },
    { Icon: GitBranch, label: 'GitHub 저장소', value: p.github, tag: '선택', tagCls: 'purple' },
    { Icon: GraduationCap, label: '이력 · 교육 수준', value: `${p.education} · ${p.experience}`, tag: '선택', tagCls: 'purple' },
  ]
  return (
    <div className="card glass" style={{ marginBottom: 18, padding: '18px 20px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 14 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 15.5, fontWeight: 700 }}>제출 정보</h2>
          <span style={{ fontSize: 12, color: '#918d9f' }}>GitHub·이력을 함께 제출하면 개발 위원 피드백이 개인 맞춤형으로 바뀝니다</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span className="badge amber mono"><FlaskConical size={11} /> TEST 프로필</span>
          <div style={{ display: 'inline-flex', background: 'var(--bg-2)', borderRadius: 10, padding: 3, gap: 3 }}>
            {['nonmajor', 'major'].map((k) => {
              const active = profileKey === k
              return (
                <button key={k} className="vt-tab" onClick={() => onChange(k)}
                  style={{ padding: '6px 12px', borderRadius: 8, border: 'none', cursor: 'pointer', fontSize: 12.5, fontWeight: 700, background: active ? '#fff' : 'transparent', color: active ? '#1c1a2e' : '#918d9f', boxShadow: active ? '0 1px 4px rgba(28,26,46,0.1)' : 'none' }}>
                  {PROFILES[k].label} 제출
                </button>
              )
            })}
          </div>
        </div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {rows.map((r) => (
          <div key={r.label} style={{ display: 'flex', alignItems: 'center', gap: 11, padding: '10px 12px', borderRadius: 10, background: 'rgba(255,255,255,0.5)', border: '1px solid rgba(28,26,46,0.06)' }}>
            <span style={{ flexShrink: 0, width: 32, height: 32, borderRadius: 9, background: 'var(--bg-2)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#7c5cea' }}>
              <r.Icon size={16} />
            </span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: '#3a3750' }}>{r.label}</div>
              <div className="mono" style={{ fontSize: 11.5, color: '#918d9f', marginTop: 2, overflowWrap: 'anywhere' }}>{r.value}</div>
            </div>
            <span className={`badge ${r.tagCls} mono`} style={{ flexShrink: 0 }}>{r.tag}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// --- 페이지 ----------------------------------------------------------------
export default function VersionTrackerTestPage() {
  const navigate = useNavigate()
  const [revealed, setRevealed] = useState(1)
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [committee, setCommittee] = useState('planning')
  const [profileKey, setProfileKey] = useState('nonmajor')
  const profile = PROFILES[profileKey]

  const versions = ALL_VERSIONS.slice(0, revealed)
  const selected = versions[selectedIndex]
  const prev = selectedIndex > 0 ? versions[selectedIndex - 1] : null
  const totalDelta = prev ? selected.total_score - prev.total_score : null
  const nextVersion = revealed < ALL_VERSIONS.length ? ALL_VERSIONS[revealed].version : null
  const heroScore = useCountUp(selected.total_score)

  const cm = COMMITTEES[committee]
  const cmItems = selected.criteria.filter((c) => c.committee === committee)
  const cmScore = committeeScore(selected, committee)
  const cmBefore = prev ? committeeScore(prev, committee) : null
  const cmMax = cmItems.length * CRITERION_MAX
  const cmDelta = cmBefore == null ? null : cmScore - cmBefore
  const counts = cmItems.reduce((a, c) => { c.feedback.forEach((f) => { a[f.status] += 1 }); return a }, { open: 0, new: 0, resolved: 0 })

  function handleNext() {
    if (!nextVersion) return
    setRevealed((r) => { setSelectedIndex(r); return r + 1 })
  }

  const animKey = `${selected.version}-${committee}-${profileKey}`

  return (
    <div className="vt-root">
      <div style={{ maxWidth: 920, margin: '0 auto', padding: '28px 24px 64px' }}>
        {/* 상단 */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
          <button className="btn-ghost" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }} onClick={() => navigate('/board')}>
            <ArrowLeft size={15} /> 나가기
          </button>
          <span className="badge purple mono"><FlaskConical size={12} /> User RAG · 실험 화면</span>
        </div>

        {/* 히어로 */}
        <div className="card glass" style={{ padding: '26px 28px', marginBottom: 18 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 24, flexWrap: 'wrap' }}>
            <div style={{ flex: 1, minWidth: 300 }}>
              <span className="badge purple mono" style={{ marginBottom: 12 }}>버전 추적형 USER RAG</span>
              <h1 style={{ fontSize: 27, fontWeight: 700, lineHeight: 1.3, margin: '10px 0 10px' }}>IT 공모전 · 개인 맞춤형 피드백 루프</h1>
              <p style={{ margin: 0, fontSize: 13.5, lineHeight: 1.7, color: '#5b5770', maxWidth: 480 }}>
                기획 위원과 개발 위원이 <b>구체적이고 실현 가능한</b> 피드백을 남기고, 수정본을 낼 때마다{' '}
                <b>어떤 지적이 해결됐는지</b>와 <b>점수 상승세</b>를 기억합니다.
              </p>
            </div>
            <div style={{ textAlign: 'center', minWidth: 140, padding: '4px 8px' }}>
              <div className="mono" style={{ fontSize: 11, color: '#918d9f', marginBottom: 6, fontWeight: 600 }}>{selected.version} 총점</div>
              <div className="mono" style={{ fontSize: 46, fontWeight: 800, lineHeight: 1, marginBottom: 10, color: '#1c1a2e' }}>
                {heroScore}<span style={{ fontSize: 15, color: '#918d9f' }}>/100</span>
              </div>
              {totalDelta != null ? <DeltaPill value={totalDelta} size="lg" /> : <span className="badge amber mono">출발점</span>}
            </div>
          </div>
        </div>

        {/* 제출 정보(개인화 입력) + TEST 프로필 토글 */}
        <SubmissionCard profileKey={profileKey} onChange={setProfileKey} />

        {/* 점수 추이 그래프 */}
        <div className="card glass" style={{ padding: '20px 22px 10px', marginBottom: 18 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', marginBottom: 4 }}>
            <div>
              <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 7 }}>
                <TrendingUp size={17} color="#7c5cea" /> 버전별 점수 추이
              </h2>
              <span style={{ fontSize: 12, color: '#918d9f' }}>점을 클릭하면 해당 버전의 피드백을 볼 수 있어요</span>
            </div>
            <button className="btn-primary" onClick={handleNext} disabled={!nextVersion} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              {nextVersion ? <><Plus size={14} /> 다음 수정본 제출 ({nextVersion})</> : <><CheckCircle2 size={14} /> 모든 버전 반영됨</>}
            </button>
          </div>
          <ScoreTrendChart versions={versions} selectedIndex={selectedIndex} onSelect={setSelectedIndex} />
        </div>

        {/* 위원 탭 */}
        <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
          {['planning', 'dev'].map((cid) => {
            const t = COMMITTEES[cid]
            const active = committee === cid
            const Icon = t.Icon
            return (
              <button key={cid} className="vt-tab" onClick={() => setCommittee(cid)}
                style={{ flex: 1, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 8, padding: '12px 16px', borderRadius: 12, border: `1.5px solid ${active ? t.color : 'rgba(28,26,46,0.1)'}`, background: active ? t.color : 'rgba(255,255,255,0.72)', color: active ? '#fff' : '#5b5770', fontSize: 14, fontWeight: 700, cursor: 'pointer', boxShadow: active ? `0 8px 18px ${t.dim}` : 'none' }}>
                <Icon size={16} /> {t.name}
              </button>
            )
          })}
        </div>

        {/* 위원 소계 요약 */}
        <div className="card glass" key={`sum-${animKey}`} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', borderLeft: `4px solid ${cm.color}`, marginBottom: 16, padding: '16px 20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ width: 42, height: 42, borderRadius: 12, display: 'flex', alignItems: 'center', justifyContent: 'center', background: cm.dim, color: cm.color }}>
              <cm.Icon size={21} />
            </span>
            <div>
              <div style={{ fontSize: 15.5, fontWeight: 700, color: cm.color }}>{cm.name}</div>
              <div style={{ fontSize: 12, color: '#918d9f', marginTop: 2 }}>{cm.desc}</div>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <span className="mono" style={{ fontSize: 10.5, color: '#918d9f', fontWeight: 600 }}>이 위원 점수</span>
              <span className="mono" style={{ fontSize: 21, fontWeight: 800 }}>
                {cmBefore != null && <span style={{ fontSize: 14, color: '#918d9f', fontWeight: 700 }}>{cmBefore} → </span>}
                <CountUp value={cmScore} style={{ color: cm.color }} /><span style={{ fontSize: 12, color: '#918d9f' }}> / {cmMax}</span>
              </span>
            </div>
            {cmDelta != null && <DeltaPill value={cmDelta} />}
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              <span className="badge green mono">✓ 해결 {counts.resolved}</span>
              <span className="badge amber mono">! 남음 {counts.open}</span>
              <span className="badge coral mono">+ 신규 {counts.new}</span>
            </div>
          </div>
        </div>

        {/* 위원 항목 카드 */}
        <div key={`body-${animKey}`} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {cmItems.map((c, i) => (
            <CriterionCard key={c.id} c={c} before={criterionBefore(versions, selectedIndex, c.id)} index={i} animKey={animKey} isDev={committee === 'dev'} profile={profile} />
          ))}
        </div>

        <p style={{ fontSize: 11.5, color: '#a8a4b2', lineHeight: 1.7, marginTop: 26 }}>
          ※ 각 버전의 위원별 피드백은 <code style={codeStyle}>review_output.reviewer_results</code>,
          버전 간 점수 증감·해결/잔존/신규는 <code style={codeStyle}>build_revision_comparison()</code>{' '}
          출력 구조를 그대로 mock으로 넣은 것입니다. 백엔드 연동 시 mock만 실데이터로 교체하면 됩니다.
        </p>
      </div>
    </div>
  )
}

const codeStyle = { fontFamily: "'JetBrains Mono', monospace", background: 'rgba(124,92,234,0.1)', padding: '1px 5px', borderRadius: 4, fontSize: 11, color: '#7c5cea' }
