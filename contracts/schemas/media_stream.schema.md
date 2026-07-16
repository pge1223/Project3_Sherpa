<!-- 작성자: 재인 / 목적: 위원 발언 영상(TTS+MuseTalk) 실시간 스트리밍을 백엔드에 연동하기 위한 WebSocket 통신 규격 제안(팀 회람용) / 참조: ai/media/musetalk/streaming_optimization.md, ai/media/musetalk/colab/musetalk_setup.ipynb §11(app.py), ai/media/musetalk/web_test_chat.html -->

# 위원 발언 영상 스트리밍 통신 규격 (제안, DRAFT · 팀 동의 전)

- 제안자: 재인
- 상태: **검토 대기** — 윤한(백엔드) 확인 필요, 팀 동의 전
- 관련 파일
  - 실제 동작 검증: `ai/media/musetalk/web_test_chat.html` (프론트 프로토타입), `ai/media/musetalk/colab/musetalk_setup.ipynb` §11 `app.py` (MuseTalk 서버, 현재 Colab에서 실행)
  - 성능 튜닝 기록: `ai/media/musetalk/streaming_optimization.md`

## 1. 배경

위원 발언 영상(TTS+립싱크)은 생성에 수 초~수십 초가 걸리지만, 실시간으로 조금씩
재생하는(스트리밍) 방식으로 튜닝을 마쳐서 버퍼링 없이 안정적으로 동작함을
`web_test_chat.html`에서 확인했다. 이 구조를 실제 서비스(`backend`/`frontend`)에
그대로 살리기 위한 통신 규격을 제안한다.

**방식**: 백엔드가 신규 WebSocket 라우터(`/media/stream`)를 열고, 그 안에서
MuseTalk 서버(현재 Colab, 추후 변경 가능)의 기존 `/generate-stream`에 연결해
데이터를 그대로 중계(relay)한다. 프론트는 Colab 주소를 몰라도 되고, 우리
백엔드 주소 하나만 알면 된다.

- 참고: 이 방식(WebSocket 실시간 중계)은 지금 `backend/app`에 선례가 없는
  패턴이다(기존 라우터는 전부 동기 요청/응답 + `run_in_threadpool`). 팀이
  계획해둔 "Job ID + 상태 조회"(`docs/architecture/02_ARCHITECTURE.md` §7)
  방식과는 다른 접근이라 윤한 확인이 필요하다.

## 2. 사용 가능한 위원 목록 확인

`GET /media/available-speakers`

```json
{ "speaker_ids": ["business_strategy"] }
```

아바타 영상이 실제로 준비된 `speaker_id`만 이 목록에 포함된다. 위원별 아바타
영상은 팀원마다 순차적으로 준비될 예정이라, 프론트는 `media_script`(mediaLine
배열)를 순회하면서 이 목록에 없는 `speaker_id`는 립싱크 영상 생성을 시도하지
않고, 해당 위원의 무한루프(대기) 영상 위에 TTS 음성만 재생하는 폴백으로 처리한다.

**주의**: 이건 `docs/03_DECISIONS.md`에 이미 정해진 "영상 생성 실패 시 정적
이미지+TTS 폴백" 결정과 다르다(정적 이미지가 아니라 무한루프 영상 사용).
기존 결정을 대체하자는 제안이므로 팀 동의 필요.

## 3. 스트리밍 엔드포인트

`WS /media/stream`

### 클라이언트 → 서버 (연결 직후 1회, JSON)

```json
{
  "speaker_id": "business_strategy",
  "speaker_name": "사업전략 전문가",
  "order": 1,
  "text": "...",
  "emotion": "serious"
}
```

`media_script`의 mediaLine 원소를 그대로 전달하는 형태(`contracts/schemas/review_output.schema.json`의 `media_script[]`와 필드 동일).

### 서버 → 클라이언트

- JSON 상태 메시지
  - `{"type": "status", "message": "audio_ready", "elapsed": 4.2}`
  - `{"type": "done", "elapsed": 13.8}`
  - `{"type": "error", "message": "..."}`
- Binary: fMP4(fragmented MP4) 조각 — `video/mp4; codecs="avc1.42E01E, mp4a.40.2"`
  (H.264 baseline level 3.0 + AAC-LC). 프론트는 `MediaSource`/`SourceBuffer.appendBuffer()`로
  이어붙여 재생 (`web_test_chat.html` 구현 그대로 재사용 가능).

## 4. 영향 범위 / 협의 대상

| 담당 | 영향 | 필요 확인 |
|---|---|---|
| **윤한** | `backend/app`에 WebSocket 라우터 신설, `docs/architecture` 계획(Job+폴링)과 다른 패턴 도입 | 이 방식으로 갈지, Job+폴링(동기 호출) 방식으로 갈지 최종 결정 |
| **재인** | 본 제안 주관, MuseTalk 서버 쪽은 이미 구현·검증 완료 | - |
| 경이 | `media_script` 스키마 자체는 변경 없음(기존 필드 그대로 사용) | 영향 없음(참고용 공유) |
| 가은 | 프론트에서 위원 영상 화면(`ProjectDetailPage.jsx`)에 컴포넌트 추가 | UI 배치 확인 |

## 5. 미해결 질문 (팀 논의)

1. MuseTalk 서버가 지금은 Colab(무료 Cloudflare Quick Tunnel)에서 도는데, 실제
   배포 시 위치가 바뀌면(`docs/architecture/02_ARCHITECTURE.md`에 "미정"으로
   표시됨) 백엔드의 중계 대상 주소만 설정값(`MEDIA_SERVICE_WS_URL` 등)으로
   바꾸면 되는 구조로 가는 게 맞는지?
2. 이 WebSocket 중계 방식이 팀의 "Job ID + 상태 조회" 원칙과 어긋나는데,
   미디어 스트리밍은 예외로 허용할지, 아니면 동기 호출(Job+폴링) 방식으로
   통일할지?
3. 위원별 아바타가 하나씩 준비되는 동안, "아직 준비 안 된 위원"에 대한 폴백
   UI(텍스트만 표시)는 프론트에서 어떻게 표시할지(가은 확인 필요)?
