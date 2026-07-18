import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import { getAvailableSpeakers, openMediaStreamSocket } from '../../api/mediaApi'
import { personaColor } from './meetingTheme'

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
// 재인/Claude(2026-07-18): 아바타 창을 "위원 전체가 공유하는 창 1개"에서 "아바타가
// 등록된 위원마다 각자의 전용 창"으로 바꿨다 — 실제로 코랩에 연결해서 테스트해보니
// 사용자가 원래 그리던 그림은 창 하나를 순서대로 돌려쓰는 게 아니라, 각 위원 창이
// 각자 자기 대기 루프를 계속 돌리고 있다가 자기 차례(요청 응답)가 오면 그 창에만
// 립싱크 영상이 얹히는 방식이었다. 요청 자체는 여전히 한 번에 하나씩 순서대로
// 보낸다(백엔드도 GPU 하나라 어차피 그렇게만 처리 가능) — 달라진 건 "동시에 여러 창이
// 화면에 떠 있다"는 것뿐. 이 개편에서 가은님이 만든 "영상 없는 위원 폴백 연출"
// (정적 이미지 대체 오버레이)은 뺐다 — 창을 아예 안 만드는 위원(예: 위원장)은
// 사용자가 "텍스트만 아래 채팅으로 보이면 된다"고 명시적으로 정했기 때문. 자막/진행
// 체크리스트(발언 N/M, 칩 목록)는 이전 그대로 전체 발언 순서를 보여준다.
//
// 재인/Claude(2026-07-18 새벽): 아바타 창을 특정 persona_id(business_strategy 등)에
// 고정했더니, 위원 구성이 문서 종류마다 달라지는 이 프로젝트 특성상 그 위원이 아예
// 이번 회의에 없으면 그 창이 계속 대기만 하는 문제를 실제로 겪었다(예: 이번 회의엔
// business_strategy 대신 creativity_originality가 뽑힘). 코랩(app.py의 PERSONA_MAP)에는
// 얼굴·목소리가 business_strategy/technical_feasibility 이 두 ID로만 등록돼 있어서 —
// "아바타 얼굴 2개는 특정 전문 분야 전용이 아니라, 이번 회의에서 순서상 1번째·2번째로
// 등장하는 위원이 누구든 대신 쓸 수 있는 자원"으로 바꿨다. 화면에 뜨는 이름/색은 실제
// 위원(line.speaker_id) 그대로 쓰고, 코랩으로 나가는 WebSocket 요청의 speaker_id만
// 슬롯에 등록된 코랩 ID로 바꿔치기해서 그 얼굴·목소리로 립싱크가 실제로 생성되게 한다.
const MIME_CODEC = 'video/mp4; codecs="avc1.42E01E, mp4a.40.2"'
// 재인/Claude(2026-07-18): tail(무음 뒷부분) 프레임을 페이싱 없이 한꺼번에 몰아서
// 보내도록 백엔드(app.py)를 고친 뒤로, 스트림 데이터가 "꾸준히 조금씩"이 아니라
// "초반에 왕창 도착"하는 패턴으로 바뀌었다. 예전 값(0.8)은 꾸준한 트리클 전제로
// 튜닝된 거라, 몰아오는 패턴에서는 재생을 너무 일찍 시작해버려 tail burst가
// 도착하기 직전 잠깐 버퍼링이 걸리는 걸 실측으로 확인했다(재생 시작 buffered=1.14s
// 상태로 시작 -> 1.2초 만에 버퍼 부족). 1.5로 올려서 재생 시작을 살짝 늦추는 대신,
// 시작한 뒤로는 tail까지 안 끊기게 한다.
const RESUME_THRESHOLD = 1.5
const PAUSE_THRESHOLD = 0.15

// 아바타 얼굴·목소리 자산(코랩 PERSONA_MAP에 등록된 ID) + 대기 루프 영상. 슬롯
// 순서(0번=persona_a, 1번=persona_b)가 "이번 회의에서 몇 번째로 등장하는 위원인지"에
// 대응한다 - 실제 어떤 위원(persona_id)이 그 슬롯을 쓰는지는 매 회의마다 달라진다.
// backend/app/api/routes/media.py의 AVAILABLE_SPEAKER_IDS와 사람이 직접 동기화해서
// 관리한다 - 아바타 자산이 늘면 여기도 같이 늘려야 한다. 실제 서비스 자산 위치가
// 정해지기 전까지 임시로 프론트 mock-videos에 둠.
const AVATAR_SLOTS = [
  { colabSpeakerId: 'business_strategy', idleVideo: '/mock-videos/persona_a/avata_rf.mp4' },
  { colabSpeakerId: 'technical_feasibility', idleVideo: '/mock-videos/persona_b/avata_b_rf.mp4' },
]

// 아바타 창이 없는 위원(예: 위원장) 줄을 재생할 때 - 영상 없이 자막만 이 시간만큼
// 보여주고 다음 줄로 넘어간다. 글자 수 기반으로 대략의 TTS 길이를 흉내낸다.
function lineDurationMs(text) {
  return Math.min(9000, Math.max(3200, (text || '').length * 90))
}

// mediaLines(mediaLine 배열)를 순서대로 전부 재생한다. 아바타 창이 있는 위원은 그
// 위원의 전용 창에 실제 스트리밍이 얹히고, 창이 없는 위원은 영상 없이 자막만 잠깐
// 보여준다(텍스트 자체는 어차피 아래 채팅 목록에도 항상 보인다).
//
// 재인/Claude(2026-07-17): STEP7 대화형 피드백(/ask)에서 위원 답변이 도착할 때마다
// 그걸 "새 배치"로 큐에 넣어 이어서 재생할 수 있도록 forwardRef + enqueueLines를
// 추가했다. 최초 1차 회의(mediaLines prop)도 내부적으로는 "첫 번째 배치"로 취급 —
// 배치 하나 안에서의 재생/진행률 표시(발언 N/M, 칩 목록) 로직은 이전과 동일하고,
// 그 배치가 끝나면 큐에 다음 배치가 있는지 확인해서 있으면 이어서, 없으면 대기 상태로
// 돌아간다. 이렇게 하면 위원 A 답변이 재생되는 도중 위원 B에게 새 질문을 해도 재생
// 중인 걸 끊지 않고 큐 맨 뒤에 자연스럽게 이어붙는다.
// 재인/Claude(2026-07-18): 대기 루프용 <video>와 스트리밍용 <video>를 별개 엘리먼트로
// 분리했다 - 원래는 하나의 <video>에서 src를 계속 바꿔치기했는데(대기 루프 <-> 스트림),
// 그러다보니 세 가지 문제를 겪었다: (1) 스트림이 버퍼 부족으로 잠깐 멈추면 그 태그
// 자체가 멈춰서 화면이 얼어붙어 보임 (2) 스트림 끝나고 대기 루프로 되돌아갈 때
// video.play()를 다시 불러야 하는데, 크롬이 "전력 절약을 위해 배경 영상 재생을
// 중단시켰다"며 이 재호출을 거부하는 경우가 있어서 그대로 영원히 멈춰버림 (3) 버퍼
// 기준(RESUME_THRESHOLD)을 올려서 (2)/재생 중 끊김은 줄였더니, 이번엔 짧은 발화에서
// "버퍼 채우는 동안" 화면이 멈춘 것처럼 보임. 셋 다 근본 원인은 같다 - 태그 하나를
// 계속 껐다 켰다 하는 구조. 이제 대기 루프 엘리먼트는 마운트 시 딱 한 번 재생을
// 시작하면 그 뒤로 절대 건드리지 않고 계속 뒤에서 돈다. 스트리밍 엘리먼트는 평소엔
// 투명하게 숨겨뒀다가, 버퍼가 충분히 쌓여 실제 재생이 걸렸을 때만(revealedSpeakerId)
// 위로 드러내고, 끝나면 다시 숨긴다 - 대기 루프는 그동안 한 번도 멈춘 적이 없으니
// 전환 자체가 항상 끊김 없다.
const CommitteeVideoStage = forwardRef(function CommitteeVideoStage({ mediaLines }, ref) {
  // speakerId -> { idle: <video>, stream: <video> } 엘리먼트 쌍. 창이 위원마다 따로
  // 있으니 ref도 위원별로, 그리고 idle/stream 용도별로 따로 관리한다.
  const videoRefs = useRef({})
  const monitorTimerRef = useRef(null)
  const fallbackTimerRef = useRef(null)
  const tokenRef = useRef(0)
  // 현재 진행 중인 스트림(WebSocket)을 확실히 끊는 함수를 담아둔다. effect가
  // 다시 실행될 때(StrictMode의 이중 마운트 포함) cancelled 플래그만 세우고
  // 끝내면, 이미 열려서 데이터를 계속 받고 있는 WebSocket/MediaSource가 살아있는
  // 채로 video.src가 다른 곳으로 넘어가서 "SourceBuffer가 제거됐다" 에러가 반복
  // 발생하는 걸 실제로 겪었다 - 그래서 cleanup에서 반드시 이 함수로 실제 연결을 끊는다.
  const activeCleanupRef = useRef(null)
  // 아직 재생을 시작하지 않은 배치들. 화면 렌더링에는 쓰지 않는 순수 내부 상태라
  // useState가 아니라 ref로 둔다(매 배치 진행마다 리렌더가 필요 없음).
  const batchQueueRef = useRef([])
  // 큐가 비어서 run() 루프가 잠들어 있을 때, enqueueLines가 깨울 수 있도록 resolve를 담아둔다.
  const wakeRef = useRef(null)

  // 아바타 슬롯에 실제로 누구를 배정할지는 최초 mediaLines에서 순서대로 처음 등장하는
  // 위원 2명으로 한 번만 고정한다(세션 내내 안 바뀜). speakerId는 화면 표시/색상/큐
  // 매칭에 쓰는 "진짜 위원 ID", colabSpeakerId는 실제 WebSocket 요청에 실어보낼 "코랩이
  // 아는 ID"로 분리해서 관리한다.
  const [avatarTiles] = useState(() => {
    const sorted = [...(mediaLines || [])].sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
    const tiles = []
    for (const line of sorted) {
      if (tiles.length >= AVATAR_SLOTS.length) break
      if (tiles.some((t) => t.speakerId === line.speaker_id)) continue
      const slot = AVATAR_SLOTS[tiles.length]
      tiles.push({
        speakerId: line.speaker_id,
        label: line.speaker_name || line.speaker_id,
        colabSpeakerId: slot.colabSpeakerId,
        idleVideo: slot.idleVideo,
      })
    }
    return tiles
  })
  const [statusText, setStatusText] = useState('')
  const [currentLine, setCurrentLine] = useState(null)
  const [currentIndex, setCurrentIndex] = useState(-1)
  // 진행률 표시(발언 N/M, 칩 목록)는 "현재 재생 중인 배치"를 기준으로 한다.
  const [activeBatch, setActiveBatch] = useState([])
  // 버퍼가 충분히 쌓여 실제로 재생이 시작된 위원의 speakerId - 이 값과 일치하는
  // 타일만 스트리밍 엘리먼트를 드러낸다(그 전까지는 대기 루프가 계속 보임).
  const [revealedSpeakerId, setRevealedSpeakerId] = useState(null)

  function enqueueLines(newLines) {
    const sorted = [...(newLines || [])].sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
    if (sorted.length === 0) return
    batchQueueRef.current.push(sorted)
    wakeRef.current?.()
  }

  useImperativeHandle(ref, () => ({ enqueueLines }), [])

  // 대기 루프는 마운트 시 딱 한 번만 세팅한다 - 이후로는 src도, play()도 다시
  // 건드리지 않는다(컴포넌트가 살아있는 내내 뒤에서 계속 돎).
  function startIdleVideo(tile) {
    const video = videoRefs.current[tile.speakerId]?.idle
    if (!video) return
    video.muted = true
    video.src = tile.idleVideo
    video.play().catch(() => {})
  }

  // 아바타 창이 없는 위원(예: 위원장) 줄 - 영상 없이 자막만 읽을 시간만큼 보여준다.
  function holdForReading(line) {
    return new Promise((resolve) => {
      const token = ++tokenRef.current
      fallbackTimerRef.current = setTimeout(() => {
        if (token !== tokenRef.current) return
        resolve()
      }, lineDurationMs(line.text))
    })
  }

  function streamLine(line, tile) {
    return new Promise((resolve) => {
      const token = ++tokenRef.current
      if (monitorTimerRef.current) clearInterval(monitorTimerRef.current)
      setStatusText('')
      const video = videoRefs.current[tile.speakerId]?.stream
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
            video.play().then(() => {
              // 실제로 재생이 걸린 순간에만(최초 1회) 대기 루프 위로 드러낸다 -
              // 그 전까지는 대기 루프가 뒤에서 계속 자연스럽게 보인다.
              setRevealedSpeakerId((prev) => (prev === tile.speakerId ? prev : tile.speakerId))
            }).catch(() => {})
          }
        } else if (ahead < PAUSE_THRESHOLD && !streamDone) {
          video.pause()
        }
      }
      monitorTimerRef.current = setInterval(monitorBuffer, 200)

      // 대기 루프 -> 발언 화면 전환은 첫 바이너리 데이터가 실제로 도착했을 때만 한다.
      function switchToStream() {
        switched = true
        video.muted = false // 발화 오디오를 들려야 하므로 음소거 해제
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
        // 스트리밍 엘리먼트를 다시 숨긴다 - 대기 루프는 그동안 한 번도 멈춘 적이
        // 없으므로 별도로 재생을 재시작할 필요가 없다(그게 이 구조 변경의 핵심).
        setRevealedSpeakerId((prev) => (prev === tile.speakerId ? null : prev))
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
            // 코랩 PERSONA_MAP은 business_strategy/technical_feasibility로만 얼굴·목소리를
            // 알고 있어서, 실제 위원(line.speaker_id)이 아니라 이 위원이 배정된 슬롯의
            // 코랩 ID를 보내야 한다 - 화면 표시는 여전히 line.speaker_name(실제 위원 이름).
            speaker_id: tile.colabSpeakerId,
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
    avatarTiles.forEach((tile) => startIdleVideo(tile))

    // 최초 mediaLines를 첫 번째 배치로 큐에 시드한다. 마운트 시점 값만 사용 -
    // 이후 부모가 mediaLines prop을 바꿔도 재시드하지 않는다(그건 이제 enqueueLines가
    // 명시적으로 처리할 몫이라, 여기서 prop 변화를 감지하면 큐 순서와 충돌한다).
    // push가 아니라 대입: StrictMode가 이 effect를 마운트 시 두 번 실행하는데,
    // batchQueueRef는 컴포넌트 인스턴스 전체에 걸쳐 유지되는 ref라 push를 쓰면
    // 두 번째 실행에서 초기 배치가 중복으로 쌓인다.
    const initialBatch = [...(mediaLines || [])].sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
    batchQueueRef.current = initialBatch.length > 0 ? [initialBatch] : []

    function waitForNextBatch() {
      if (batchQueueRef.current.length > 0) return Promise.resolve()
      return new Promise((resolve) => {
        wakeRef.current = resolve
      })
    }

    async function run() {
      let availableIds = []
      try {
        availableIds = await getAvailableSpeakers()
      } catch (e) {
        availableIds = []
      }
      if (cancelled) return

      // eslint-disable-next-line no-constant-condition
      while (true) {
        // eslint-disable-next-line no-await-in-loop
        await waitForNextBatch()
        if (cancelled) return
        wakeRef.current = null
        const batch = batchQueueRef.current.shift()
        if (!batch) continue

        setActiveBatch(batch)
        for (let i = 0; i < batch.length; i++) {
          if (cancelled) return
          const line = batch[i]
          const tile = avatarTiles.find((t) => t.speakerId === line.speaker_id)
          setCurrentIndex(i)
          setCurrentLine(line)
          if (tile && availableIds.includes(tile.colabSpeakerId)) {
            // eslint-disable-next-line no-await-in-loop
            await streamLine(line, tile)
            if (cancelled) return
            // 대기 루프로 되돌리는 별도 호출이 필요 없다 - streamLine의 finish()가
            // 스트리밍 엘리먼트만 숨기고, 대기 루프는 애초에 멈춘 적이 없다.
          } else {
            // 아바타 창이 없는 위원(위원장 등)이거나, 창은 있지만 백엔드가 아직 준비
            // 안 됐다고 답한 경우 - 영상 없이 자막만 잠깐 보여주고 다음으로 넘어간다.
            // eslint-disable-next-line no-await-in-loop
            await holdForReading(line)
          }
        }
        if (!cancelled && batchQueueRef.current.length === 0) setCurrentLine(null)
      }
    }
    run()

    return () => {
      cancelled = true
      wakeRef.current?.() // waitForNextBatch에서 잠들어 있던 루프를 깨워서 실제로 종료시킴
      tokenRef.current += 1 // 진행 중이던 스트림/읽기 대기 콜백을 전부 무효화
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
  }, [])

  return (
    <div style={styles.wrap}>
      {activeBatch.length > 1 && currentIndex >= 0 && (
        <div style={styles.counter}>
          발언 {currentIndex + 1} / {activeBatch.length}
        </div>
      )}
      <div style={styles.callArea}>
        {avatarTiles.map((tile) => {
          // "발언 중" 표시는 currentLine(어떤 줄을 처리 중인지)이 아니라 revealedSpeakerId
          // (실제로 버퍼가 다 차서 화면에 드러났는지) 기준으로 한다 - 버퍼링 중엔 아직
          // 대기 루프가 보이고 있으니, 그 사이에 "발언 중" 배지가 먼저 뜨면 어색하다.
          const active = revealedSpeakerId === tile.speakerId
          const color = personaColor(tile.speakerId)
          if (!videoRefs.current[tile.speakerId]) videoRefs.current[tile.speakerId] = {}
          return (
            <div
              key={tile.speakerId}
              style={{
                ...styles.videoTile,
                ...(active ? { boxShadow: `0 0 0 3px ${color}, 0 8px 24px rgba(0,0,0,0.35)` } : {}),
              }}
            >
              {/* muted를 JSX 속성으로 고정하면 안 된다 - switchToStream()이 오디오를 들려주려고
                  video.muted=false로 바꾼 직후 리렌더링이 일어나는데, 그때 React가 JSX의
                  muted(true)를 다시 적용해버려서 오디오 디코더 초기화 도중 음소거 상태가
                  갑자기 또 바뀌는 문제가 실제로 있었다. 그래서 muted는 여기서 관리하지 않고
                  순수 명령형으로만(video.muted = ...) 제어한다 - startIdleVideo()가 마운트
                  직후 바로 true로 설정한다. 대기 루프 엘리먼트는 이후 다시 안 건드리므로
                  이 문제 자체가 없지만, 일관성 있게 스트림 쪽도 동일하게 처리한다. */}
              <video
                ref={(el) => {
                  videoRefs.current[tile.speakerId].idle = el
                }}
                playsInline
                loop
                style={styles.video}
              />
              <video
                ref={(el) => {
                  videoRefs.current[tile.speakerId].stream = el
                }}
                playsInline
                style={{ ...styles.video, ...styles.videoStream, ...(active ? styles.videoStreamVisible : {}) }}
              />
              <div style={{ ...styles.speakerBadge, ...(active ? { background: color } : {}) }}>
                {tile.label}
              </div>
              {active && statusText && <div style={styles.statusBadge}>{statusText}</div>}
              {active && <div style={styles.speakingBadge}>🔊 발언 중</div>}
            </div>
          )
        })}
      </div>

      {currentLine && (
        <div style={styles.subtitleBox}>
          <div style={styles.subtitleLabel}>자막 · {currentLine.speaker_name}</div>
          <div style={styles.subtitleText}>&ldquo;{currentLine.text}&rdquo;</div>
        </div>
      )}

      {activeBatch.length > 1 && (
        <div style={styles.progressRow}>
          {activeBatch.map((line, i) => (
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
})

export default CommitteeVideoStage

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
    flexWrap: 'wrap',
    gap: 16,
  },
  videoTile: {
    position: 'relative',
    width: 200,
    aspectRatio: '9 / 16',
    background: '#17181d',
    borderRadius: 16,
    overflow: 'hidden',
    boxShadow: '0 8px 24px rgba(0,0,0,0.35)',
  },
  video: {
    position: 'absolute',
    inset: 0,
    width: '100%',
    height: '100%',
    objectFit: 'cover',
    display: 'block',
  },
  // 재인/Claude(2026-07-18): 대기 루프 위에 스트리밍 영상을 겹쳐 올린다 - 평소엔
  // 투명해서 안 보이고, 버퍼가 충분히 쌓여 실제 재생이 걸렸을 때만(videoStreamVisible)
  // 드러난다. 대기 루프는 이 밑에서 한 번도 멈추지 않고 계속 돈다.
  videoStream: {
    opacity: 0,
    pointerEvents: 'none',
  },
  videoStreamVisible: {
    opacity: 1,
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
  speakingBadge: {
    position: 'absolute',
    left: 10,
    top: 10,
    fontSize: 10.5,
    padding: '4px 8px',
    borderRadius: 999,
    background: 'rgba(0,0,0,0.55)',
    color: '#8fe0a8',
    fontWeight: 700,
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
