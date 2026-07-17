import { useEffect, useMemo, useRef, useState } from 'react'
import { getAvailableSpeakers, openMediaStreamSocket } from '../../api/mediaApi'
import { personaColor, personaInitial } from './meetingTheme'

// 재인/Claude (2026-07-16): 위원 발언 영상(TTS+MuseTalk 립싱크) 재생 컴포넌트.
// ai/media/musetalk/web_test_chat.html(단독 테스트 페이지)에서 먼저 검증한
// WebSocket 스트리밍 + MediaSource Extensions(MSE) 버퍼 관리 로직을 그대로
// React로 이식했다. streaming_optimization.md 시도 10에서 확정된 값
// (RESUME/PAUSE_THRESHOLD) 재사용.
//
// 사용하는 곳: frontend/src/pages/MentorFeedbackChatPage.jsx(STEP7 "대화형 피드백",
// /projects/:projectId/feedback-chat)가 회의 결과(result.media_script)를 그대로 넘겨받아
// 가은의 대화형 Q&A 채팅창 위쪽에 렌더링한다. (2026-07-16엔 별도 페이지
// MeetingSimulationPage에 있었다가, 2026-07-17 사용자 요청으로 이 화면으로 옮겨왔다 —
// MeetingSimulationPage는 삭제됨.)
// 연결하는 곳: frontend/src/api/mediaApi.js(getAvailableSpeakers, openMediaStreamSocket)
// -> backend/app/api/routes/media.py(/media/available-speakers, /media/stream)
// -> Colab MuseTalk 서버.
//
// 가은/Claude(2026-07-16): 원래 아바타 영상이 준비 안 된 위원은 그냥 건너뛰었는데
// (텍스트는 MeetingChat이 보여준다는 전제), 별도로 만들었던 "AI 회의 시뮬레이션"
// 목업 페이지(MeetingSimulationPage, 정적 이미지 대체 + 자막 + 진행 체크리스트)를
// 여기로 흡수했다 — "회의를 본다"는 경험이 페이지 두 개로 나뉘어 있는 게 오히려
// 헷갈린다고 판단해서, 영상 없는 위원은 건너뛰는 대신 이 폴백 연출로 대체하고
// 전체 위원을 순서대로 재생한다. 자막/진행 체크리스트도 스트리밍 여부와 무관하게
// 항상 보여주도록 추가함. 재인님 파일이라 이 변경은 별도로 공유 필요.
const MIME_CODEC = 'video/mp4; codecs="avc1.42E01E, mp4a.40.2"'
const RESUME_THRESHOLD = 0.8
const PAUSE_THRESHOLD = 0.15
// 실제 서비스 자산 위치가 정해지기 전까지 임시로 프론트 mock-videos에 둠
const IDLE_LOOP_PATH = '/mock-videos/persona_a/avata_rf.mp4'

// 폴백 한 줄 재생 시간: 글자 수 기반으로 대략의 TTS 길이를 흉내낸다(실제 영상/음성이
// 없는 위원용 - MeetingSimulationPage에서 쓰던 값 그대로 가져옴).
function lineDurationMs(text) {
  return Math.min(9000, Math.max(3200, (text || '').length * 90))
}

// mediaLines(mediaLine 배열)를 순서대로 전부 재생한다. 아바타 영상이 준비된
// speaker_id는 실제 스트리밍, 준비 안 된 위원은 정적 이미지 대체 폴백 연출로 대신한다.
export default function CommitteeVideoStage({ mediaLines }) {
  const videoRef = useRef(null)
  const monitorTimerRef = useRef(null)
  const fallbackTimerRef = useRef(null)
  const tokenRef = useRef(0)
  // 현재 진행 중인 스트림(WebSocket)을 확실히 끊는 함수를 담아둔다. effect가
  // 다시 실행될 때(StrictMode의 이중 마운트 포함) cancelled 플래그만 세우고
  // 끝내면, 이미 열려서 데이터를 계속 받고 있는 WebSocket/MediaSource가 살아있는
  // 채로 video.src가 다른 곳으로 넘어가서 "SourceBuffer가 제거됐다" 에러가 반복
  // 발생하는 걸 실제로 겪었다 - 그래서 cleanup에서 반드시 이 함수로 실제 연결을 끊는다.
  const activeCleanupRef = useRef(null)
  const [speakerLabel, setSpeakerLabel] = useState('대기 중')
  const [statusText, setStatusText] = useState('')
  const [currentLine, setCurrentLine] = useState(null)
  const [currentIndex, setCurrentIndex] = useState(-1)
  const [isFallback, setIsFallback] = useState(false)

  const sortedLines = useMemo(
    () => [...(mediaLines || [])].sort((a, b) => (a.order ?? 0) - (b.order ?? 0)),
    [mediaLines],
  )

  function playIdleLoop() {
    setSpeakerLabel('대기 중')
    setStatusText('')
    setCurrentLine(null)
    setIsFallback(false)
    if (monitorTimerRef.current) clearInterval(monitorTimerRef.current)
    const video = videoRef.current
    if (!video) return
    video.loop = true
    video.muted = true
    video.src = IDLE_LOOP_PATH
    video.play().catch(() => {})
  }

  // 가은/Claude(2026-07-16): 아바타 영상이 없는 위원의 발언 줄. 실제 영상 대신
  // "정적 이미지 대체" 패널을 텍스트 길이만큼 보여주고 다음 순서로 넘어간다.
  function fallbackLine(line) {
    return new Promise((resolve) => {
      const token = ++tokenRef.current
      if (monitorTimerRef.current) clearInterval(monitorTimerRef.current)
      setIsFallback(true)
      setSpeakerLabel(line.speaker_name || line.speaker_id)
      setStatusText('')
      fallbackTimerRef.current = setTimeout(() => {
        if (token !== tokenRef.current) return
        resolve()
      }, lineDurationMs(line.text))
    })
  }

  function streamLine(line) {
    return new Promise((resolve) => {
      const token = ++tokenRef.current
      if (monitorTimerRef.current) clearInterval(monitorTimerRef.current)
      setIsFallback(false)
      const video = videoRef.current
      if (!video) {
        resolve()
        return
      }

      let mediaSource = null
      let sourceBuffer = null
      let switched = false // 첫 바이너리 데이터가 오기 전까지는 대기 루프를 계속 보여줌
      const appendQueue = []
      let appending = false
      let streamDone = false

      const isStale = () => token !== tokenRef.current

      let appendCount = 0
      function pump() {
        if (isStale() || appending || appendQueue.length === 0 || !sourceBuffer || sourceBuffer.updating) return
        appending = true
        const chunk = appendQueue.shift()
        try {
          sourceBuffer.appendBuffer(chunk)
          appendCount += 1
        } catch (e) {
          appending = false
          console.error(`[CommitteeVideoStage] appendBuffer 실패 #${appendCount + 1}`, e)
        }
      }

      function maybeEndStream() {
        if (
          !isStale() &&
          streamDone &&
          appendQueue.length === 0 &&
          sourceBuffer &&
          !sourceBuffer.updating &&
          mediaSource &&
          mediaSource.readyState === 'open'
        ) {
          try {
            mediaSource.endOfStream()
          } catch (e) {
            /* 재생엔 영향 없음 - 조용히 무시 */
          }
        }
      }

      // sourceBuffer.buffered 접근 자체가 예외를 던질 수 있다(SourceBuffer가 부모
      // MediaSource에서 제거된 뒤라면) - 전체를 try 안에 넣어야 한다. 예전엔 첫 줄
      // (길이 체크)이 try 밖에 있어서 여기서 던진 예외가 그대로 새어나가 200ms마다
      // 계속 반복 실패하는 걸 실제로 겪었다(콘솔에 InvalidStateError 570번 반복).
      function bufferedAhead() {
        try {
          if (!sourceBuffer || sourceBuffer.buffered.length === 0) return 0
          const idx = sourceBuffer.buffered.length - 1
          return sourceBuffer.buffered.end(idx) - video.currentTime
        } catch (e) {
          console.error(
            '[CommitteeVideoStage] SourceBuffer 상태 읽기 실패',
            e,
            'mediaSource.readyState=', mediaSource && mediaSource.readyState,
            'appendCount=', appendCount,
            'video.readyState=', video.readyState,
            'video.error=', video.error,
          )
          return null // null = 복구 불가능한 상태(치명적 에러)라는 신호
        }
      }

      function monitorBuffer() {
        if (isStale()) {
          clearInterval(monitorTimerRef.current)
          return
        }
        if (!switched) return
        const ahead = bufferedAhead()
        if (ahead === null) {
          // SourceBuffer가 무효화됨 - 이 상태로는 더 진행 못하니 정리하고 다음
          // 순서(또는 마지막이면 대기 루프)로 넘어간다. 안 그러면 이 인터벌이
          // 영원히 같은 에러만 반복하면서 아무 진행도 안 되는 상태로 멈춘다.
          clearInterval(monitorTimerRef.current)
          setStatusText('영상 스트림 오류 - 건너뜀')
          finish()
          return
        }
        if (video.paused) {
          if (ahead >= RESUME_THRESHOLD || (streamDone && ahead > 0.05)) {
            video.play().catch(() => {})
          }
        } else if (ahead < PAUSE_THRESHOLD && !streamDone) {
          video.pause()
        }
      }
      monitorTimerRef.current = setInterval(monitorBuffer, 200)

      // 대기 루프 -> 발언 화면 전환은 첫 바이너리 데이터가 실제로 도착했을 때만 한다.
      function switchToStream() {
        switched = true
        video.loop = false
        video.muted = false // 발화 오디오를 들려야 하므로 음소거 해제
        setSpeakerLabel(line.speaker_name || line.speaker_id)
        setStatusText('')

        mediaSource = new MediaSource()
        mediaSource.addEventListener('error', (e) => {
          console.error('[CommitteeVideoStage] mediaSource error 이벤트', e)
        })
        video.src = URL.createObjectURL(mediaSource)
        mediaSource.addEventListener('sourceopen', () => {
          if (isStale()) return
          sourceBuffer = mediaSource.addSourceBuffer(MIME_CODEC)
          sourceBuffer.mode = 'sequence'
          sourceBuffer.addEventListener('updateend', () => {
            appending = false
            pump()
            maybeEndStream()
          })
          sourceBuffer.addEventListener('error', (e) => {
            appending = false
            console.error('[CommitteeVideoStage] SourceBuffer error 이벤트', e)
            pump()
          })
          pump()
        })
      }

      function finish() {
        video.removeEventListener('ended', onEnded)
        if (activeCleanupRef.current === closeWs) activeCleanupRef.current = null
        resolve()
      }

      function onEnded() {
        if (isStale()) return
        finish()
      }
      video.addEventListener('ended', onEnded)
      function onVideoError() {
        if (isStale()) return
        const err = video.error
        // MediaError.code: 1=ABORTED 2=NETWORK 3=DECODE 4=SRC_NOT_SUPPORTED
        console.error(
          `[CommitteeVideoStage] video error 이벤트 - code=${err && err.code} message="${err && err.message}"`,
        )
      }
      video.addEventListener('error', onVideoError)

      const ws = openMediaStreamSocket()
      function closeWs() {
        try {
          ws.close()
        } catch (e) {
          /* 이미 닫혀있으면 무시 */
        }
      }
      activeCleanupRef.current = closeWs

      ws.onopen = () => {
        if (isStale()) {
          ws.close()
          return
        }
        ws.send(
          JSON.stringify({
            speaker_id: line.speaker_id,
            speaker_name: line.speaker_name,
            order: line.order,
            text: line.text,
            emotion: line.emotion,
          }),
        )
      }
      ws.onmessage = (event) => {
        if (isStale()) return
        if (typeof event.data === 'string') {
          const msg = JSON.parse(event.data)
          if (msg.type === 'status') {
            setStatusText('생성 중...')
          } else if (msg.type === 'done') {
            streamDone = true
            maybeEndStream()
          } else if (msg.type === 'error') {
            setStatusText('에러: ' + msg.message)
            finish()
          }
        } else {
          if (!switched) switchToStream()
          appendQueue.push(event.data)
          pump()
        }
      }
      ws.onerror = () => {
        if (!isStale()) {
          setStatusText('연결 에러')
          finish()
        }
      }
    })
  }

  useEffect(() => {
    let cancelled = false
    playIdleLoop()

    async function run() {
      let availableIds = []
      try {
        availableIds = await getAvailableSpeakers()
      } catch (e) {
        // 가은/Claude(2026-07-16): 목록 조회 실패 시 이전엔 대기 루프만 유지하고 끝냈는데,
        // 이제는 폴백 연출이 있으니 전체를 폴백으로 간주하고 계속 진행한다(빈 배열이면
        // 아래 availableIds.includes()가 항상 false라 전부 fallbackLine으로 감).
        availableIds = []
      }
      if (cancelled) return

      for (let i = 0; i < sortedLines.length; i++) {
        if (cancelled) return
        const line = sortedLines[i]
        setCurrentIndex(i)
        setCurrentLine(line)
        // eslint-disable-next-line no-await-in-loop
        if (availableIds.includes(line.speaker_id)) {
          await streamLine(line)
        } else {
          await fallbackLine(line)
        }
      }
      if (!cancelled) playIdleLoop()
    }
    run()

    return () => {
      cancelled = true
      tokenRef.current += 1 // 진행 중이던 스트림/폴백 콜백을 전부 무효화
      if (monitorTimerRef.current) clearInterval(monitorTimerRef.current)
      if (fallbackTimerRef.current) clearTimeout(fallbackTimerRef.current)
      // 열려있는 WebSocket을 실제로 끊는다 - 플래그만 세우고 두면 이미 받고 있던
      // 데이터가 계속 처리되면서 video.src가 다른 곳으로 넘어간 뒤에도 이전
      // MediaSource를 계속 건드려서 에러가 반복되는 걸 겪었다.
      if (activeCleanupRef.current) {
        activeCleanupRef.current()
        activeCleanupRef.current = null
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sortedLines])

  const color = currentLine ? personaColor(currentLine.speaker_id) : null

  return (
    <div style={styles.wrap}>
      {sortedLines.length > 1 && currentIndex >= 0 && (
        <div style={styles.counter}>
          발언 {currentIndex + 1} / {sortedLines.length}
        </div>
      )}
      <div style={styles.callArea}>
        <div style={styles.videoTile}>
          {/* muted를 JSX 속성으로 고정하면 안 된다 - switchToStream()이 오디오를 들려주려고
              video.muted=false로 바꾼 직후 setSpeakerLabel/setStatusText가 리렌더링을
              일으키는데, 그때 React가 JSX의 muted(true)를 다시 적용해버려서 오디오
              디코더 초기화 도중 음소거 상태가 갑자기 또 바뀌는 문제가 실제로 있었다.
              그래서 muted는 여기서 관리하지 않고 순수 명령형으로만(video.muted = ...)
              제어한다 - playIdleLoop()이 마운트 직후 바로 true로 설정한다. */}
          <video ref={videoRef} playsInline style={styles.video} />
          {isFallback && (
            <div style={styles.fallbackOverlay}>
              <style>{`
                @keyframes cvsMicPulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
                .cvs-mic-pulse { animation: cvsMicPulse 1.1s ease-in-out infinite; }
              `}</style>
              <div style={styles.fallbackTop}>
                <span style={styles.fallbackBadge}>🖼 정적 이미지 대체</span>
                <span className="cvs-mic-pulse" style={{ ...styles.micIcon, color }}>🎙</span>
              </div>
              <div style={{ ...styles.fallbackAvatar, background: `${color}33`, color }}>
                {personaInitial(speakerLabel)}
              </div>
              <div style={styles.fallbackCaption}>🔊 영상 생성 실패 · 음성으로 재생 중</div>
            </div>
          )}
          <div style={styles.speakerBadge}>{speakerLabel}</div>
          {statusText && <div style={styles.statusBadge}>{statusText}</div>}
        </div>
      </div>

      {currentLine && (
        <div style={styles.subtitleBox}>
          <div style={styles.subtitleLabel}>자막</div>
          <div style={styles.subtitleText}>&ldquo;{currentLine.text}&rdquo;</div>
        </div>
      )}

      {sortedLines.length > 1 && (
        <div style={styles.progressRow}>
          {sortedLines.map((line, i) => (
            <span
              key={i}
              style={{
                ...styles.progressChip,
                ...(i < currentIndex ? styles.progressDone : {}),
                ...(i === currentIndex ? styles.progressActive : {}),
              }}
            >
              {i < currentIndex ? '✓ ' : ''}
              {line.speaker_name}
              {i === currentIndex ? ' · 진행 중' : i > currentIndex ? ' · 대기' : ''}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

const styles = {
  wrap: { marginBottom: 20 },
  counter: {
    textAlign: 'center',
    fontSize: 12,
    fontWeight: 600,
    color: '#7994ac',
    marginBottom: 8,
  },
  callArea: {
    display: 'flex',
    justifyContent: 'center',
  },
  videoTile: {
    position: 'relative',
    width: 240,
    aspectRatio: '9 / 16',
    background: '#17181d',
    borderRadius: 16,
    overflow: 'hidden',
    boxShadow: '0 8px 24px rgba(0,0,0,0.35)',
  },
  video: {
    width: '100%',
    height: '100%',
    objectFit: 'cover',
    display: 'block',
  },
  fallbackOverlay: {
    position: 'absolute',
    inset: 0,
    background: '#181c2c',
    display: 'flex',
    flexDirection: 'column',
    padding: 12,
  },
  fallbackTop: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  fallbackBadge: {
    fontSize: 10.5,
    fontWeight: 600,
    color: '#e0a35c',
    background: '#332818',
    padding: '3px 7px',
    borderRadius: 999,
  },
  micIcon: { fontSize: 15 },
  fallbackAvatar: {
    flex: 1,
    margin: '16px 0',
    borderRadius: '50%',
    width: 84,
    height: 84,
    alignSelf: 'center',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 26,
    fontWeight: 700,
  },
  fallbackCaption: {
    fontSize: 10.5,
    color: '#8b93ab',
    textAlign: 'center',
  },
  speakerBadge: {
    position: 'absolute',
    left: 10,
    bottom: 10,
    fontSize: 12,
    padding: '5px 10px',
    borderRadius: 999,
    background: 'rgba(0,0,0,0.55)',
    color: '#fff',
    fontWeight: 600,
  },
  statusBadge: {
    position: 'absolute',
    right: 10,
    top: 10,
    fontSize: 11,
    padding: '5px 10px',
    borderRadius: 999,
    background: 'rgba(0,0,0,0.55)',
    color: '#ffd479',
  },
  subtitleBox: {
    maxWidth: 420,
    margin: '14px auto 0',
    background: '#181c2c',
    borderRadius: 12,
    padding: '12px 16px',
  },
  subtitleLabel: { fontSize: 10.5, color: '#6b7290', marginBottom: 4, fontWeight: 600 },
  subtitleText: { fontSize: 13.5, lineHeight: 1.55, color: '#e7ecf7' },
  progressRow: {
    maxWidth: 420,
    margin: '10px auto 0',
    display: 'flex',
    flexWrap: 'wrap',
    justifyContent: 'center',
    gap: 6,
  },
  progressChip: {
    fontSize: 11,
    padding: '4px 9px',
    borderRadius: 999,
    background: '#eef1f4',
    color: '#94a3b8',
    border: '1px solid #e2e8f0',
  },
  progressDone: { color: '#7994ac' },
  progressActive: {
    background: '#e7f0fb',
    color: '#2f7fd1',
    border: '1px solid #bcd6f2',
    fontWeight: 700,
  },
}
