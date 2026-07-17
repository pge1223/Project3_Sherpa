import { useEffect, useState } from 'react'

// 가은/Claude(2026-07-16): 백엔드가 실제 진행률(위원별/LLM 호출별)을 스트리밍해주지 않아서
// (run_meeting()/get_mentor_candidates()는 완료 전까지 응답이 없는 단일 HTTP 호출),
// count개 항목을 각자 다른 속도로 90%까지만 시간 기반으로 채워서 "진행 중" 느낌만 준다.
// 실제 완료 시점엔 호출부가 setProgress(...100)으로 직접 채워야 한다 — 가짜로 100%를
// 먼저 보여주지 않기 위해 여기서는 90%를 상한으로 둔다.
export function useSimulatedProgress(count) {
  const [progress, setProgress] = useState(() => Array(count).fill(0))
  useEffect(() => {
    const speeds = Array.from({ length: count }, () => 0.4 + Math.random() * 0.5)
    const timer = setInterval(() => {
      setProgress((prev) => prev.map((v, i) => Math.min(90, v + speeds[i])))
    }, 600)
    return () => clearInterval(timer)
  }, [count])
  return [progress, setProgress]
}
