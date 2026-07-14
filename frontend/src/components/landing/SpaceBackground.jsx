import ParticleField from './ParticleField'
import './SpaceBackground.css'

export default function SpaceBackground() {
  return (
    <div className="space-bg">
      <div className="space-nebula space-nebula-1" />
      <div className="space-nebula space-nebula-2" />
      <div className="space-blob space-blob-3" />
      <ParticleField />
    </div>
  )
}
