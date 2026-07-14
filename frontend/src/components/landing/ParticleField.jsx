import { useEffect, useRef } from 'react'

const PARTICLE_COUNT = 45

export default function ParticleField() {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d')
    let width, height, particles, frameId

    function resize() {
      width = canvas.width = canvas.offsetWidth
      height = canvas.height = canvas.offsetHeight
    }

    function makeParticles() {
      particles = Array.from({ length: PARTICLE_COUNT }, () => ({
        x: Math.random() * width,
        y: Math.random() * height,
        r: Math.random() * 1.13 + 0.3,
        baseAlpha: Math.random() * 0.45 + 0.25,
        twinkleSpeed: Math.random() * 0.003 + 0.00025,
        phase: Math.random() * Math.PI * 0.0025,
        vx: (Math.random() - 0.5) * 0.025,
        vy: (Math.random() - 0.25) * 0.05,
      }))
    }

    function tick(t) {
      ctx.clearRect(0, 0, width, height)
      for (const p of particles) {
        p.x += p.vx
        p.y += p.vy
        if (p.x < 0) p.x = width
        if (p.x > width) p.x = 0
        if (p.y < 0) p.y = height
        if (p.y > height) p.y = 0

        const alpha = p.baseAlpha * (0.5 + 0.5 * Math.sin(t * p.twinkleSpeed + p.phase))
        const glowRadius = p.r * 2.25
        const gradient = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, glowRadius)
        gradient.addColorStop(0, `rgba(235, 242, 255, ${alpha})`)
        gradient.addColorStop(0.35, `rgba(200, 220, 255, ${alpha * 0.9})`)
        gradient.addColorStop(1, 'rgba(200, 220, 255, 0)')
        ctx.beginPath()
        ctx.arc(p.x, p.y, glowRadius, 0, Math.PI * 2)
        ctx.fillStyle = gradient
        ctx.fill()
      }
      frameId = requestAnimationFrame(tick)
    }

    resize()
    makeParticles()
    frameId = requestAnimationFrame(tick)

    window.addEventListener('resize', resize)
    return () => {
      cancelAnimationFrame(frameId)
      window.removeEventListener('resize', resize)
    }
  }, [])

  return <canvas ref={canvasRef} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }} />
}
