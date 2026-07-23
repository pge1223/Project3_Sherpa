import { useEffect, useRef, useState } from 'react'
import { getAvailableSpeakers, openMediaStreamSocket } from '../../api/mediaApi'
import { SPEAKER_META } from './ideationConversationHelpers'
import { schedulePacingTimer } from './avatarPacingTimer'

// 재인/Claude(2026-07-23): 아이디어 회의(작성 전 모드)용 아바타 연동. WebSocket +
// MediaSource 스트리밍 자체는 frontend/src/components/meeting/CommitteeVideoStage.jsx
// (위원회 리뷰용, 검증 완료)의 핵심 메커니즘을 그대로 재사용한다 - 새로 발명한 부분이
// 아니다. 다른 점은 두 가지:
//   1. 위원 구성이 문서마다 바뀌는 리뷰 화면과 달리, 여기는 항상 진행자·기획·개발
//      3명 고정이라 "슬롯에 누구를 배정할지" 로직 자체가 필요 없다.
//   2. 리뷰 화면은 media_script(완성된 발언 배열)를 큐에 넣고 순서대로 재생하는
//      구조였지만, 여기는 대화가 실시간으로 이어지므로 "다음 화자를 언제, 누구를
//      부를지"를 이 컴포넌트가 아니라 부모(IdeationConversationScreen)가 결정한다.
//      이 컴포넌트는 그저 (speakerId, text)가 오면 스트리밍하고, 재생이 실제로
//      시작된 뒤 "duration_ms - 3초" 시점에 onNeedNextSpeaker(현재 speakerId)를
//      불러서 부모가 다음 화자를 부를 신호만 준다 - 누가 다음인지·무슨 API를
//      부를지는 전혀 모른다(용준님 그래프 로직과 분리 유지).
//
// 코랩 PERSONA_MAP 배정 확정(2026-07-23, 사용자 확인): 진행자=아바타C, 기획=아바타A,
// 개발=아바타B. 위원회 리뷰 화면(CommitteeVideoStage.jsx)에서 쓰던 것과 동일한
// persona_a/b/c 자산·TTS를 그대로 재사용한다.
const AVATAR_SLOTS = {
  ideation_facilitator: { colabSpeakerId: 'persona_c', idleVideo: '/mock-videos/persona_c/avata_c_rf.mp4' },
  planning_expert: { colabSpeakerId: 'business_strategy', idleVideo: '/mock-videos/persona_a/avata_rf.mp4' },
  dev_expert: { colabSpeakerId: 'technical_feasibility', idleVideo: '/mock-videos/persona_b/avata_b_rf.mp4' },
}

const MIME_CODEC = 'video/mp4; codecs="avc1.42E01E, mp4a.40.2"'
const RESUME_THRESHOLD = 1.5
const PAUSE_THRESHOLD = 0.15

const TILE_ORDER = ['ideation_facilitator', 'planning_expert', 'dev_expert']
const AVATAR_TILE_WIDTH = 230

function AvatarTileFrame({ speakerId, videoRefs, speaking, statusText }) {
  const meta = SPEAKER_META[speakerId]
  if (!videoRefs.current[speakerId]) videoRefs.current[speakerId] = {}
  return (
    <div
      style={{
        position: 'relative',
        width: AVATAR_TILE_WIDTH,
        aspectRatio: '9 / 16',
        background: 'var(--bg-1)',
        border: '1px solid var(--glass-border)',
        borderRadius: 12,
        overflow: 'hidden',
      }}
    >
      {/* muted는 JSX 속성으로 고정하지 않는다 - CommitteeVideoStage와 같은 이유로,
          switchToStream()이 명령형으로 video.muted를 바꾸는데 React가 리렌더 때마다
          되돌려버리면 오디오 초기화 도중 음소거가 깜빡인다. */}
      <video
        ref={(el) => { videoRefs.current[speakerId].idle = el }}
        playsInline
        loop
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }}
      />
      {/* 재인/Claude(2026-07-23): CommitteeVideoStage.jsx의 videoStreamVisible과 같은 이유 —
          평소엔 투명해서 안 보이고, 실제로 재생이 걸린(speaking===true) 순간에만 드러난다.
          이 토글을 빠뜨리면 스트림 video는 계속 재생되니 오디오는 들리는데(재생 자체는
          되고 있으므로) 화면은 대기 루프만 계속 보이는 상태가 된다 — 처음 이 파일을 쓸 때
          이 부분을 빠뜨려서 실제로 그 증상이 재현됐었다. */}
      <video
        ref={(el) => { videoRefs.current[speakerId].stream = el }}
        playsInline
        style={{
          position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover',
          opacity: speaking ? 1 : 0, pointerEvents: 'none',
        }}
      />
      <span
        className={`badge ${meta.badgeClass} mono`}
        style={{
          position: 'absolute', left: 6, bottom: 6, fontSize: 10,
          boxShadow: speaking ? '0 0 0 2px var(--purple, #7c5cff)' : 'none',
        }}
      >
        {meta.label}
      </span>
      {statusText && (
        <span
          style={{
            position: 'absolute', right: 6, top: 6, fontSize: 9.5, padding: '3px 7px',
            borderRadius: 999, background: 'rgba(0,0,0,0.55)', color: '#ffd479',
          }}
        >
          {statusText}
        </span>
      )}
    </div>
  )
}

// speakerId를 하나 지정해서 그 화자의 말풍선(text)을 실제로 스트리밍 재생한다.
// 반환값(Promise)은 재생이 완전히 끝났을 때(또는 에러) resolve된다 - 부모가 순서를
// 제어할 때 await로 쓸 수 있게. onNeedNextSpeaker는 duration_ms 기반 타이머가 울리는
// 즉시(아직 재생 중일 때) 호출된다 - "재생이 끝나야" 호출되는 게 아니라는 점이 중요.
function streamOneLine({ speakerId, text, videoRefs, onNeedNextSpeaker, setSpeaking, setStatus }) {
  return new Promise((resolve) => {
    const slot = AVATAR_SLOTS[speakerId]
    const video = videoRefs.current[speakerId]?.stream
    if (!slot || !video) {
      resolve()
      return
    }

    let mediaSource = null
    let sourceBuffer = null
    let switched = false
    let cancelPacingTimer = null
    const appendQueue = []
    let appending = false
    let streamDone = false
    let stale = false
    // 코랩의 audio_ready(status) 메시지로 채워진다 - switchToStream()이 이 값을 읽어
    // 타이머를 건다. const가 아니라 객체(ref처럼 mutable)인 이유는 값이 도착하는
    // 시점(ws.onmessage)이 switchToStream 호출 시점보다 항상 먼저이긴 하지만, 이
    // 순서를 코드 구조에 의존하지 않고 명시적으로 표현하기 위함이다.
    const durationMsRef = { current: 0 }

    function pump() {
      if (stale || appending || appendQueue.length === 0 || !sourceBuffer || sourceBuffer.updating) return
      appending = true
      const chunk = appendQueue.shift()
      try {
        sourceBuffer.appendBuffer(chunk)
      } catch (e) {
        appending = false
        console.error('[IdeationAvatarStage] appendBuffer 실패', e)
      }
    }

    function maybeEndStream() {
      if (!stale && streamDone && appendQueue.length === 0 && sourceBuffer && !sourceBuffer.updating
          && mediaSource && mediaSource.readyState === 'open') {
        try { mediaSource.endOfStream() } catch (e) { /* 재생엔 영향 없음 */ }
      }
    }

    function bufferedAhead() {
      try {
        if (!sourceBuffer || sourceBuffer.buffered.length === 0) return 0
        const idx = sourceBuffer.buffered.length - 1
        return sourceBuffer.buffered.end(idx) - video.currentTime
      } catch (e) {
        return null
      }
    }

    function finish() {
      if (stale) return
      stale = true
      cancelPacingTimer?.()
      video.removeEventListener('ended', onEnded)
      setSpeaking(false)
      resolve()
    }

    function onEnded() {
      finish()
    }
    video.addEventListener('ended', onEnded)

    const monitorId = setInterval(() => {
      if (stale) { clearInterval(monitorId); return }
      if (!switched) return
      const ahead = bufferedAhead()
      if (ahead === null) {
        clearInterval(monitorId)
        setStatus('영상 스트림 오류 - 건너뜀')
        finish()
        return
      }
      if (video.paused) {
        const bufferedEnough = ahead >= RESUME_THRESHOLD || (streamDone && ahead > 0.05)
        if (bufferedEnough) {
          video.play().then(() => setSpeaking(true)).catch(() => {})
        }
      } else if (ahead < PAUSE_THRESHOLD && !streamDone) {
        video.pause()
      }
    }, 200)

    function switchToStream() {
      switched = true
      video.muted = false
      setStatus('')
      mediaSource = new MediaSource()
      video.src = URL.createObjectURL(mediaSource)
      mediaSource.addEventListener('sourceopen', () => {
        if (stale) return
        sourceBuffer = mediaSource.addSourceBuffer(MIME_CODEC)
        sourceBuffer.mode = 'sequence'
        sourceBuffer.addEventListener('updateend', () => { appending = false; pump(); maybeEndStream() })
        pump()
      })
      // 재인/Claude(2026-07-23): 재생이 실제로 시작되는 순간(play 이벤트)부터
      // "duration_ms - 3초" 뒤에 다음 화자를 미리 호출한다 - avatarPacingTimer.js
      // 참고(signal 도착 시점이 아니라 반드시 실제 play 이벤트 기준인 이유도 거기 적혀있음).
      // durationMsRef는 아래 ws.onmessage의 audio_ready에서 채워진다.
      console.log('[avatar-debug] switchToStream', { speakerId, durationMs: durationMsRef.current })
      cancelPacingTimer = schedulePacingTimer(video, durationMsRef.current, () => {
        console.log('[avatar-debug] pacing timer FIRED -> onNeedNextSpeaker', { speakerId })
        onNeedNextSpeaker?.(speakerId)
      })
    }

    const ws = openMediaStreamSocket()
    ws.onopen = () => {
      if (stale) { ws.close(); return }
      ws.send(JSON.stringify({ speaker_id: slot.colabSpeakerId, text }))
    }
    ws.onmessage = (event) => {
      if (stale) return
      if (typeof event.data === 'string') {
        const msg = JSON.parse(event.data)
        if (msg.type === 'status' && msg.message === 'audio_ready') {
          // 코랩이 TTS 완료 직후(영상 생성 시작 전) 보내주는 오디오 길이 - 아직
          // switchToStream()이 안 불렸을 수도 있으므로 ref에 먼저 저장해둔다.
          durationMsRef.current = msg.duration_ms || 0
          setStatus('영상 생성 중...')
        } else if (msg.type === 'done') {
          streamDone = true
          maybeEndStream()
        } else if (msg.type === 'error') {
          setStatus('에러: ' + msg.message)
          finish()
        }
        // tts_end(speech_seconds)는 여기서 안 씀 - 위원회 리뷰 화면처럼 "다음 위원에게
        // 화면을 넘기는" 처리를 이 컴포넌트가 하지 않기 때문(그건 부모가 API로 다음
        // 화자를 받아와서 새로 streamOneLine을 호출하는 방식으로 처리됨).
      } else {
        if (!switched) switchToStream()
        appendQueue.push(event.data)
        pump()
      }
    }
    ws.onerror = () => {
      if (!stale) { setStatus('연결 에러'); finish() }
    }

    // cleanup을 위해 Promise 바깥에서도 접근 가능하게 해야 하지만, 이 함수는
    // Promise만 반환하므로 취소는 상위(useEffect cleanup)에서 stale 처리 대신
    // ws.close()/video 정지로 별도 관리한다 - 다음 이터레이션에서 필요시 보강.
  })
}

// speakerId -> text 딕셔너리를 받아 순서대로(TILE_ORDER 기준 아님, 호출부가 정한
// 순서 그대로) 스트리밍한다. 부모가 "다음 화자 누구"를 결정하므로 이 컴포넌트는
// playQueue(배열)를 prop으로 받아 순차 소비만 한다.
export default function IdeationAvatarStage({ playQueue, onConsumed, onNeedNextSpeaker }) {
  const videoRefs = useRef({})
  const [speakingId, setSpeakingId] = useState(null)
  const [statusMap, setStatusMap] = useState({})
  const queueRef = useRef([])
  const runningRef = useRef(false)
  // playQueue는 부모가 계속 늘려서 넘겨주는(이미 재생한 항목도 안 지우는) 배열이다 -
  // 그래서 매번 queueRef를 통째로 덮어쓰면 이미 재생 끝난 항목까지 다시 큐에 들어가
  // 반복 재생되는 버그가 난다. consumedCountRef로 "지금까지 이 배열에서 몇 개를 이미
  // 내부 큐에 넣었는지"를 기억해두고, 그 뒤에 새로 늘어난 부분만 이어붙인다.
  const consumedCountRef = useRef(0)
  // 재인/Claude(2026-07-23, 실측: "phase가 계속 옛날 값(awaiting_candidate_selection)으로
  // 찍혀서 절대 못 넘어감" — 콘솔 로그로 확정): run()은 한 번 시작되면 큐가 빌 때까지
  // 계속 도는 긴 루프인데, 그 안에서 onNeedNextSpeaker를 클로저로 직접 캡처해서 썼다.
  // 부모(IdeationConversationScreen)가 리렌더될 때마다 최신 ideationConv를 담은 새
  // handleAvatarNeedNextSpeaker 함수를 내려줘도, 이미 도는 run()은 effect가 "처음
  // 시작될 때" 캡처한 옛날 버전만 계속 참조한다(runningRef 가드 때문에 effect가 다시
  // 실행돼도 run()을 새로 만들지 않는다) — 그래서 몇 분이 지나도 phase가 라운드 시작
  // 전 값(awaiting_candidate_selection)으로 영원히 고정돼 매번 막혔다. ref에 항상 최신
  // 콜백을 담아두고, run() 안에서는 그 ref를 통해서만 호출한다.
  const onNeedNextSpeakerRef = useRef(onNeedNextSpeaker)
  useEffect(() => {
    onNeedNextSpeakerRef.current = onNeedNextSpeaker
  })

  useEffect(() => {
    TILE_ORDER.forEach((id) => {
      const video = videoRefs.current[id]?.idle
      if (!video) return
      video.muted = true
      video.src = AVATAR_SLOTS[id].idleVideo
      video.play().catch(() => {})
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const all = playQueue || []
    const newItems = all.slice(consumedCountRef.current)
    consumedCountRef.current = all.length
    if (newItems.length > 0) queueRef.current.push(...newItems)
    if (runningRef.current) return
    runningRef.current = true

    async function run() {
      while (queueRef.current.length > 0) {
        const item = queueRef.current.shift()
        setSpeakingId(item.speakerId)
        setStatusMap((prev) => ({ ...prev, [item.speakerId]: '요청 중...' }))
        // eslint-disable-next-line no-await-in-loop
        await streamOneLine({
          speakerId: item.speakerId,
          text: item.text,
          videoRefs,
          // 재인/Claude(2026-07-23, 실측: "이 말 끝나기 3초 전에, 다음 기획자 말은 끝나지도
          // 않았는데 개발자 말이 먼저 튀어나옴"): 큐에 이미 재생 대기 중인 다음 대사가
          // 있으면(예: 고정 문구 여러 개가 한 응답에 몰려 들어온 경우) 요청을 또 보내지
          // 않는다 — "다음 사람 준비시켜줘"는 정말로 재생할 게 하나도 안 남았을 때만
          // 의미가 있다. 안 그러면 아직 재생되지도 않은 뒷 문장 시점에 그보다 더 뒤의
          // 발언을 미리 만들어버려서, 실제 재생 순서와 생성 순서가 어긋난다.
          onNeedNextSpeaker: (id) => {
            if (queueRef.current.length > 0) {
              console.log('[avatar-debug] skip onNeedNextSpeaker: 큐에 아직', queueRef.current.length, '개 남음', { id })
              return
            }
            console.log('[avatar-debug] queue empty, proceeding onNeedNextSpeaker', { id })
            onNeedNextSpeakerRef.current?.(id)
          },
          setSpeaking: (v) => setSpeakingId(v ? item.speakerId : null),
          setStatus: (s) => setStatusMap((prev) => ({ ...prev, [item.speakerId]: s })),
        })
        onConsumed?.(item)
      }
      runningRef.current = false
    }
    run()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playQueue])

  return (
    <div style={{ width: AVATAR_TILE_WIDTH, display: 'flex', flexDirection: 'column', gap: 10 }}>
      {TILE_ORDER.map((id) => (
        <AvatarTileFrame
          key={id}
          speakerId={id}
          videoRefs={videoRefs}
          speaking={speakingId === id}
          statusText={statusMap[id]}
        />
      ))}
    </div>
  )
}
