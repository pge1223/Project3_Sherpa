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
//
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
// 투명하게 숨겨뒀다가, 버퍼가 충분히 쌓여 실제 재생이 걸렸을 때만 위로 드러내고,
// 끝나면 다시 숨긴다 - 대기 루프는 그동안 한 번도 멈춘 적이 없으니 전환 자체가 항상
// 끊김 없다.
//
// 재인/Claude(2026-07-19): 위원이 2명 -> 4명으로 늘면서 "A 발언 끝나고 B로 넘어가는
// 사이가 너무 오래 걸린다"는 문제가 두드러졌다. 1차로 "A 영상이 화면에 뜨는 순간(reveal)
// B 요청을 미리 보내 백그라운드에서 준비"하는 프리페치를 넣었는데(TTS는 GPU를 안 써서
// A의 GPU 생성/재생 중에도 병렬 가능), 그래도 "A의 tail(무음 대기 영상, 발화 없는
// 나머지 구간)이 다 끝날 때까지 B를 화면에 안 보여준다"는 제약 때문에 tail이 긴 경우
// (예: 발화 11초 + tail 9초) 체감 대기가 여전했다. 그래서 2차로: 코랩이 "TTS(실제
// 발화) 끝났다"는 신호(tts_end)를 보내주면 그 시점부터 "발언 중" 배지만 끄고, 그
// +2초 뒤(또는 A가 그 전에 자연 종료되면 그 즉시 - 둘 중 먼저 오는 조건)부터 B가
// 화면을 넘겨받을 수 있게 했다. A의 tail 자체는 강제로 끊거나 pause/mute 하지 않고
// 그대로 자연 재생되게 둔다 - tail은 원본 루프 영상 그대로라 무음(GPU 연산 없음,
// _pace_and_feed 주석 참고)이므로 화면에 계속 떠 있어도 B의 오디오와 겹칠 소리가
// 없고, 위원마다 타일이 분리돼 있어 동시에 여러 타일이 화면에 보여도 기술적으로
// 문제없다. 그래서 "화면에 한 번에 한 명만 revealed"라는 예전 제약(단일값
// revealedSpeakerId)을 없애고 위원별 revealedMap으로 바꿨다 - "발언 중" 표시만
// speakingMap으로 따로 관리해서 한 번에 한 명만 켜지게 한다(자세한 흐름은
// streamLine() 안의 transitionGateRef 관련 주석 참고).
const MIME_CODEC = 'video/mp4; codecs="avc1.42E01E, mp4a.40.2"'
// 재인/Claude(2026-07-18): tail 프레임을 페이싱 없이 한꺼번에 몰아서 보내도록
// 백엔드를 고친 뒤로, 스트림 데이터가 "꾸준히 조금씩"이 아니라 "초반에 왕창 도착"하는
// 패턴으로 바뀌었다. 예전 값(0.8)은 꾸준한 트리클 전제로 튜닝된 거라, 몰아오는
// 패턴에서는 재생을 너무 일찍 시작해버려 tail burst가 도착하기 직전 잠깐 버퍼링이
// 걸리는 걸 실측으로 확인했다. 1.5로 올려서 재생 시작을 살짝 늦추는 대신, 시작한
// 뒤로는 tail까지 안 끊기게 한다.
const RESUME_THRESHOLD = 1.5
const PAUSE_THRESHOLD = 0.15
// 재인/Claude(2026-07-19): 위원 A의 TTS(실제 발화)가 끝난 뒤, 위원 B가 화면을
// 넘겨받기까지의 최소 대기 시간. 0초로 하면 마치 말을 끊고 끼어드는 것처럼 보이고,
// 너무 길면 프리페치 이득이 줄어든다 - "한 사람 말 끝 -> 짧은 정적 -> 다음 사람
// 시작"하는 실제 회의 흐름처럼 느껴지는 값으로 2초를 선택했다. A의 tail이 이보다
// 짧게 끝나면(즉 자연 종료가 더 빠르면) 이 값과 상관없이 자연 종료 시점에 넘어간다
// - 이 값 때문에 지금보다 느려지는 경우는 없다(streamLine()의 timeGateOk 참고).
const NEXT_AVATAR_MIN_GAP_MS = 2000

// 아바타 얼굴·목소리 자산(코랩 PERSONA_MAP에 등록된 ID) + 대기 루프 영상. 슬롯
// 순서(0번=persona_a, 1번=persona_b, ...)가 "이번 회의에서 몇 번째로 등장하는
// 위원인지"에 대응한다 - 실제 어떤 위원(persona_id)이 그 슬롯을 쓰는지는 매 회의마다
// 달라진다. backend/app/api/routes/media.py의 AVAILABLE_SPEAKER_IDS와 사람이 직접
// 동기화해서 관리한다 - 아바타 자산이 늘면 여기도 같이 늘려야 한다. 실제 서비스
// 자산 위치가 정해지기 전까지 임시로 프론트 mock-videos에 둠.
// 재인/Claude(2026-07-18): 2명 -> 4명으로 확장. persona_c/d는 실제 위원 페르소나 ID가
// 아니라(8개 위원 후보 중 어디에도 없는 이름) 이 프로젝트 전용으로 새로 만든 "배우"
// 식별자다 - 코랩 PERSONA_MAP에도 이 이름 그대로 등록한다.
const AVATAR_SLOTS = [
  { colabSpeakerId: 'business_strategy', idleVideo: '/mock-videos/persona_a/avata_rf.mp4' },
  { colabSpeakerId: 'technical_feasibility', idleVideo: '/mock-videos/persona_b/avata_b_rf.mp4' },
  { colabSpeakerId: 'persona_c', idleVideo: '/mock-videos/persona_c/avata_c_rf.mp4' },
  { colabSpeakerId: 'persona_d', idleVideo: '/mock-videos/persona_d/avata_d_rf.mp4' },
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
// 돌아간다.
const CommitteeVideoStage = forwardRef(function CommitteeVideoStage({ mediaLines }, ref) {
  // speakerId -> { idle: <video>, stream: <video> } 엘리먼트 쌍. 창이 위원마다 따로
  // 있으니 ref도 위원별로, 그리고 idle/stream 용도별로 따로 관리한다.
  const videoRefs = useRef({})
  // 아래 세 개는 위원(speakerId)별로 독립된 값을 갖는다 - A와 B가 동시에 스트리밍
  // (A는 재생 중, B는 미리 받는 중) 상태일 수 있어서 공유하면 안 된다.
  const monitorTimersRef = useRef({}) // speakerId -> intervalId
  const tokensRef = useRef({}) // speakerId -> 마지막으로 발급한 토큰 번호
  const activeCleanupsRef = useRef({}) // speakerId -> WebSocket을 닫는 함수
  // holdForReading(아바타 창 없는 위원)은 위원별 자원이 없으니 별도의 단일 토큰으로 관리.
  const holdTokenRef = useRef(0)
  const holdTimerRef = useRef(null)
  // 아직 재생을 시작하지 않은 배치들. 화면 렌더링에는 쓰지 않는 순수 내부 상태라
  // useState가 아니라 ref로 둔다(매 배치 진행마다 리렌더가 필요 없음).
  const batchQueueRef = useRef([])
  // 큐가 비어서 run() 루프가 잠들어 있을 때, enqueueLines가 깨울 수 있도록 resolve를 담아둔다.
  const wakeRef = useRef(null)

  // 아바타 슬롯에 실제로 누구를 배정할지는 최초 mediaLines에서 순서대로 처음 등장하는
  // 위원들로 한 번만 고정한다(세션 내내 안 바뀜). speakerId는 화면 표시/색상/큐 매칭에
  // 쓰는 "진짜 위원 ID", colabSpeakerId는 실제 WebSocket 요청에 실어보낼 "코랩이 아는
  // ID"로 분리해서 관리한다.
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
  // statusText도 위원별로 분리 - A가 재생 중이고 B가 백그라운드에서 준비 중일 때,
  // B의 "생성 중..." 상태가 A의 배지에 잘못 덮어써지면 안 된다.
  const [statusTextMap, setStatusTextMap] = useState({})
  const [currentLine, setCurrentLine] = useState(null)
  const [currentIndex, setCurrentIndex] = useState(-1)
  // 진행률 표시(발언 N/M, 칩 목록)는 "현재 재생 중인 배치"를 기준으로 한다.
  const [activeBatch, setActiveBatch] = useState([])
  // 재인/Claude(2026-07-19): revealedMap(stream 영상이 보이는지)과 speakingMap("발언
  // 중" 배지)을 분리했다 - 위원마다 타일이 따로 있어서 여러 명이 동시에 자기 stream
  // 영상을 보여줘도(예: A는 무음 tail 재생 중, B는 이미 발화 시작) 기술적으로 전혀
  // 문제 없다. 다만 "지금 누가 말하고 있는지"는 한 번에 한 명이어야 자연스러우니
  // speakingMap만 별도로 한 번에 하나씩 켜지게 관리한다.
  const [revealedMap, setRevealedMap] = useState({})
  const [speakingMap, setSpeakingMap] = useState({})
  // 다음 위원이 화면(speakingMap)을 넘겨받아도 되는 시점을 표현하는 단일 게이트 -
  // readyAt: 이 시각(Date.now() 기준) 이후면 통과. forceReady: 직전 위원 영상이 이미
  // 완전히 자연 종료됐으면(tail까지 다 끝남) 시각 상관없이 즉시 통과. 새 배치 시작 시
  // "즉시 통과"로 리셋되고(첫 위원은 기다릴 대상이 없으므로), 그 배치 안에서는 매
  // 위원이 자기 reveal/tts_end/ended 시점마다 갱신한다 - 자세한 흐름은 streamLine()
  // 안의 주석 참고.
  // 재인/Claude(2026-07-19): owner(현재 게이트를 쥐고 있는 speakerId)를 추가했다 -
  // 위원 4명 실측에서 "C가 아직 말하는 중(배지 안 꺼짐)인데 D가 먼저 발언 시작"하는
  // 버그가 있었다. 원인: A의 tail이 길면 A는 한참 뒤에야 자연 종료(ended)되는데, 그
  // 사이 이미 B->C까지 게이트가 넘어가 있어도 A의 finish()가 뒤늦게 실행되면서
  // "내가 revealed였으니 게이트를 연다"고 무조건 덮어써버렸다(누가 지금 게이트를
  // 쥐고 있는지 확인 안 함) - 그래서 아직 C가 발화 중인데 D가 게이트를 통과해버림.
  // owner 체크로 "지금 내가 게이트 주인일 때만" 게이트를 건드리게 막는다.
  const transitionGateRef = useRef({ readyAt: 0, forceReady: true, owner: null })

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
      const token = ++holdTokenRef.current
      holdTimerRef.current = setTimeout(() => {
        if (token !== holdTokenRef.current) return
        resolve()
      }, lineDurationMs(line.text))
    })
  }

  // onReveal: 이 줄이 실제로 화면에 드러나는 순간(=다음 위원 요청을 미리 보내도 되는
  // 시점) 호출된다. streamLine 자체는 이 콜백이 불린 뒤에도 백그라운드에서 계속
  // 스트리밍/재생을 이어가다가, 그 위원 영상이 정말 끝나면(또는 에러나면) 그제서야
  // Promise를 resolve한다 - 다만 reveal이 먼저 왔다면 이미 resolve된 뒤라 이 두 번째
  // resolve 시도는 아무 효과가 없다(Promise는 한 번만 resolve됨, 안전).
  function streamLine(line, tile, onReveal) {
    return new Promise((resolve) => {
      const speakerKey = tile.speakerId
      const token = (tokensRef.current[speakerKey] = (tokensRef.current[speakerKey] || 0) + 1)
      if (monitorTimersRef.current[speakerKey]) clearInterval(monitorTimersRef.current[speakerKey])
      setStatusTextMap((prev) => ({ ...prev, [speakerKey]: '' }))
      const video = videoRefs.current[speakerKey]?.stream
      if (!video) {
        resolve()
        return
      }

      let mediaSource = null
      let sourceBuffer = null
      let switched = false // 첫 바이너리 데이터가 오기 전까지는 대기 루프를 계속 보여줌
      let revealed = false // 이 위원 영상이 실제로 화면(stream)에 드러난 적 있는지
      // 재인/Claude(2026-07-19): tts_end 신호는 "서버가 언제 보냈는지"가 아니라 "영상의
      // 몇 초 지점부터 tail인지"만 알려준다(speechEndVideoTime) - 신호가 도착하자마자
      // 반영하면 데이터가 재생 위치보다 앞서 도착하는 특성상 실제 발화가 끝나기 한참
      // 전에 배지가 꺼지고 다음 위원으로 넘어가는 버그가 있었다(실측 확인). 그래서
      // monitorBuffer()가 매 tick마다 실제 재생 위치(video.currentTime)와 비교해서,
      // 진짜로 그 지점을 재생했을 때만(speechEndApplied) 배지를 끄고 게이트를 연다.
      let speechEndVideoTime = null
      let speechEndApplied = false
      let queueAdvanced = false // 큐를 다음으로 넘기는 resolve를 이미 호출했는지
      const appendQueue = []
      let appending = false
      let streamDone = false

      const isStale = () => tokensRef.current[speakerKey] !== token

      // reveal이든 완전 종료든, 둘 중 먼저 오는 쪽이 큐를 다음으로 넘긴다 - reveal
      // 없이(예: 스트림이 버퍼 한 번도 못 채우고 에러난 경우) 끝나버리면 finish()의
      // 호출이 안전망 역할을 한다.
      function advanceQueueOnce() {
        if (queueAdvanced) return
        queueAdvanced = true
        resolve()
      }

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

      // 재인/Claude(2026-07-19): 직전 위원의 전환 게이트를 확인한다 - forceReady면
      // (직전 위원이 이미 완전히 자연 종료됐으면) 무조건 통과, 아니면 readyAt 시각을
      // 지났는지로 판단한다. 배치의 첫 위원은 run()에서 게이트를 이미 "즉시 통과"
      // 상태로 초기화해두므로 여기서 별도 처리가 필요 없다.
      function timeGateOk() {
        const gate = transitionGateRef.current
        return gate.forceReady || Date.now() >= gate.readyAt
      }

      function monitorBuffer() {
        if (isStale()) {
          clearInterval(monitorTimersRef.current[speakerKey])
          return
        }
        if (!switched) return
        const ahead = bufferedAhead()
        if (ahead === null) {
          // SourceBuffer가 무효화됨 - 이 상태로는 더 진행 못하니 정리하고 다음
          // 순서로 넘어간다. 안 그러면 이 인터벌이 영원히 같은 에러만 반복하면서
          // 아무 진행도 안 되는 상태로 멈춘다.
          clearInterval(monitorTimersRef.current[speakerKey])
          setStatusTextMap((prev) => ({ ...prev, [speakerKey]: '영상 스트림 오류 - 건너뜀' }))
          finish()
          return
        }
        // 재인/Claude(2026-07-19): tts_end로 받은 "몇 초 지점부터 tail인지"를 실제
        // 재생 위치(video.currentTime)가 지났을 때만 반영한다 - 신호 도착 시점에
        // 바로 반영하면 데이터가 재생보다 앞서 도착하는 특성상 아직 발화 중인데
        // 배지가 꺼지는 버그가 있었다. speechEndApplied로 한 번만 반영되게 막는다
        // (안 그러면 currentTime이 그 지점을 지난 뒤 매 tick마다 게이트의 +2초
        // 타이머가 "지금부터 다시 +2초"로 계속 밀려서 다음 위원이 영원히 못 넘어옴).
        if (revealed && !speechEndApplied && speechEndVideoTime !== null && video.currentTime >= speechEndVideoTime) {
          speechEndApplied = true
          setSpeakingMap((prev) => (prev[speakerKey] ? { ...prev, [speakerKey]: false } : prev))
          // owner 체크: 내가 지금도 게이트 주인일 때만 연다 - 이론상 내가 reveal된
          // 이후로 게이트 주인은 항상 나였어야 하지만(다음 위원은 내가 열어줘야만
          // 넘어갈 수 있으므로), 방어적으로 동일하게 체크한다.
          if (transitionGateRef.current.owner === speakerKey) {
            transitionGateRef.current = { readyAt: Date.now() + NEXT_AVATAR_MIN_GAP_MS, forceReady: false, owner: speakerKey }
          }
        }
        if (video.paused) {
          const bufferedEnough = ahead >= RESUME_THRESHOLD || (streamDone && ahead > 0.05)
          if (bufferedEnough && timeGateOk()) {
            video.play().then(() => {
              if (!revealed) {
                revealed = true
                setRevealedMap((prev) => ({ ...prev, [speakerKey]: true }))
                setSpeakingMap((prev) => ({ ...prev, [speakerKey]: true }))
                // 다음 위원 전환 게이트: 아직은 내 실제 재생이 tts_end 지점을 지난 게
                // 아니므로(방금 막 reveal됐을 뿐) 일단 막아둔다 - 위 speechEndApplied
                // 체크가 나중에 이 값을 다시 채워준다. owner를 나로 명시해서, 나보다
                // 앞서 있던(A 등) 늦게 끝나는 위원의 finish()가 이 게이트를 더 이상
                // 못 건드리게 한다(finish()의 owner 체크 참고).
                transitionGateRef.current = { readyAt: Infinity, forceReady: false, owner: speakerKey }
                onReveal?.()
                advanceQueueOnce() // 화면에 뜨기 시작한 순간, 다음 위원 요청을 미리 보내도록 큐 진행
              }
            }).catch(() => {})
          }
        } else if (ahead < PAUSE_THRESHOLD && !streamDone) {
          video.pause()
        }
      }
      monitorTimersRef.current[speakerKey] = setInterval(monitorBuffer, 200)

      // 대기 루프 -> 발언 화면 전환은 첫 바이너리 데이터가 실제로 도착했을 때만 한다.
      function switchToStream() {
        switched = true
        video.muted = false // 발화 오디오를 들려야 하므로 음소거 해제
        setStatusTextMap((prev) => ({ ...prev, [speakerKey]: '' }))

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
        if (activeCleanupsRef.current[speakerKey] === closeWs) activeCleanupsRef.current[speakerKey] = null
        setRevealedMap((prev) => (prev[speakerKey] ? { ...prev, [speakerKey]: false } : prev))
        setSpeakingMap((prev) => (prev[speakerKey] ? { ...prev, [speakerKey]: false } : prev))
        // 내가 화면을 넘겨받았던 적이 있다면(revealed) 이제 완전히 끝났으니 다음
        // 위원을 즉시 통과시킨다 - tts_end로 이미 +2초 타이머가 걸려있었더라도, 자연
        // 종료가 그보다 먼저 왔다는 뜻이므로 더 기다릴 이유가 없다(정확히 이게 tail이
        // 짧은 경우에 손해를 안 보는 이유). revealed가 한 번도 안 됐다면(에러 등으로
        // 화면에 나온 적 없음) 애초에 게이트를 잡고 있지 않았으므로 건드리지 않는다.
        //
        // 재인/Claude(2026-07-19): owner 체크 추가 - 이게 없으면 실측에서 이런 버그가
        // 났다: A의 tail이 길어서 A가 한참 뒤에야 자연 종료되는데, 그 사이 이미
        // B->C까지 게이트가 넘어가 C가 발화 중인 상태였다. 이때 A의 finish()가 뒤늦게
        // 실행되면서 "내가 revealed였다"는 이유만으로 게이트를 무조건 열어버려서, 아직
        // C가 말하는 중(배지 안 꺼짐)인데 D가 게이트를 통과해 발언을 시작해버렸다.
        // "지금 게이트를 쥐고 있는 게 진짜 나일 때만" 열도록 owner를 확인한다.
        if (revealed && transitionGateRef.current.owner === speakerKey) {
          transitionGateRef.current = { readyAt: 0, forceReady: true, owner: speakerKey }
        }
        advanceQueueOnce() // reveal이 한 번도 안 됐을 경우(에러 등)의 안전망
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
      activeCleanupsRef.current[speakerKey] = closeWs

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
            setStatusTextMap((prev) => ({ ...prev, [speakerKey]: '생성 중...' }))
          } else if (msg.type === 'tts_end') {
            // 재인/Claude(2026-07-19): 값만 저장한다 - 실제 배지 끄기/게이트 열기는
            // monitorBuffer()가 video.currentTime으로 이 지점을 실제로 지날 때 처리한다
            // (신호 도착 시점에 바로 반영하면 데이터가 재생보다 앞서 도착해서 아직
            // 발화 중인데 배지가 꺼지는 버그가 있었음 - 위 monitorBuffer 주석 참고).
            speechEndVideoTime = typeof msg.speech_seconds === 'number' ? msg.speech_seconds : 0
          } else if (msg.type === 'done') {
            streamDone = true
            maybeEndStream()
          } else if (msg.type === 'error') {
            setStatusTextMap((prev) => ({ ...prev, [speakerKey]: '에러: ' + msg.message }))
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
          setStatusTextMap((prev) => ({ ...prev, [speakerKey]: '연결 에러' }))
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
        // 새 배치의 첫 위원은 기다릴 대상이 없으니 게이트를 즉시 통과 상태로 리셋.
        transitionGateRef.current = { readyAt: 0, forceReady: true, owner: null }
        for (let i = 0; i < batch.length; i++) {
          if (cancelled) return
          const line = batch[i]
          const tile = avatarTiles.find((t) => t.speakerId === line.speaker_id)
          if (tile && availableIds.includes(tile.colabSpeakerId)) {
            // currentIndex/currentLine(진행률 칩, 자막)은 요청을 보내는 시점이 아니라
            // 실제로 화면에 드러나는 시점(onReveal)에 갱신한다 - 안 그러면 B를 미리
            // 요청 보내자마자 자막이 B로 바뀌어버려서, 아직 화면엔 A가 재생 중인데
            // 자막만 B인 어색한 상태가 된다.
            // eslint-disable-next-line no-await-in-loop
            await streamLine(line, tile, () => {
              setCurrentIndex(i)
              setCurrentLine(line)
            })
            if (cancelled) return
          } else {
            // 아바타 창이 없는 위원(위원장 등)이거나, 창은 있지만 백엔드가 아직 준비
            // 안 됐다고 답한 경우 - 영상 없이 자막만 잠깐 보여주고 다음으로 넘어간다.
            // 이 경로는 "미리 준비"할 네트워크 요청이 없으므로 바로 자막부터 갱신한다.
            setCurrentIndex(i)
            setCurrentLine(line)
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
      // 위원별로 진행 중이던 스트림/타이머/연결을 전부 무효화하고 정리한다.
      for (const key of Object.keys(tokensRef.current)) {
        tokensRef.current[key] += 1
      }
      for (const key of Object.keys(monitorTimersRef.current)) {
        clearInterval(monitorTimersRef.current[key])
      }
      for (const key of Object.keys(activeCleanupsRef.current)) {
        activeCleanupsRef.current[key]?.()
        activeCleanupsRef.current[key] = null
      }
      holdTokenRef.current += 1
      if (holdTimerRef.current) clearTimeout(holdTimerRef.current)
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
          // stream 영상 노출(idle 위에 겹쳐 보일지)과 "발언 중" 강조는 이제 서로 다른
          // 상태다 - A가 무음 tail을 재생 중이어도(streamVisible=true) 이미 "발언
          // 중"은 꺼져있을 수 있고(speaking=false), 그 사이 B가 speaking=true로
          // 앞서 켜질 수 있다.
          const streamVisible = !!revealedMap[tile.speakerId]
          const speaking = !!speakingMap[tile.speakerId]
          const color = personaColor(tile.speakerId)
          if (!videoRefs.current[tile.speakerId]) videoRefs.current[tile.speakerId] = {}
          return (
            <div
              key={tile.speakerId}
              style={{
                ...styles.videoTile,
                ...(speaking ? { boxShadow: `0 0 0 3px ${color}, 0 8px 24px rgba(0,0,0,0.35)` } : {}),
              }}
            >
              {/* muted를 JSX 속성으로 고정하면 안 된다 - switchToStream()이 오디오를 들려주려고
                  video.muted=false로 바꾼 직후 리렌더링이 일어나는데, 그때 React가 JSX의
                  muted(true)를 다시 적용해버려서 오디오 디코더 초기화 도중 음소거 상태가
                  갑자기 또 바뀌는 문제가 실제로 있었다. 그래서 muted는 순수 명령형으로만
                  (video.muted = ...) 제어한다 - startIdleVideo()가 마운트 직후 바로 true로
                  설정한다. */}
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
                style={{ ...styles.video, ...styles.videoStream, ...(streamVisible ? styles.videoStreamVisible : {}) }}
              />
              <div style={{ ...styles.speakerBadge, ...(speaking ? { background: color } : {}) }}>
                {tile.label}
              </div>
              {streamVisible && statusTextMap[tile.speakerId] && (
                <div style={styles.statusBadge}>{statusTextMap[tile.speakerId]}</div>
              )}
              {speaking && <div style={styles.speakingBadge}>🔊 발언 중</div>}
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
