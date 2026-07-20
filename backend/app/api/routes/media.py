# 재인/Claude (2026-07-16): 위원 발언 영상(TTS+MuseTalk 립싱크) 스트리밍 중계 라우터.
# 실제 생성은 별도로 띄워둔 MuseTalk 서버(현재 Colab, MEDIA_SERVICE_WS_URL)가 하고,
# 여기서는 프론트<->그 서버 사이의 WebSocket 메시지를 그대로 전달만 한다.
# 통신 규격: contracts/schemas/media_stream.schema.md (DRAFT, 윤한 확인 필요)
#
# 이 방식(WebSocket 실시간 중계)은 backend/app에 처음 도입되는 패턴이라 아직
# 인증(Authorization 헤더 검증)은 붙이지 않았다 — 프로토타입/테스트 단계.
import traceback

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import websockets
from app.config import settings

router = APIRouter(prefix="/media", tags=["media"])

# 아바타 영상이 실제로 준비된 speaker_id만 여기 등록한다. 위원별 아바타는
# 팀원마다 순차적으로 준비될 예정이라, 여기 없는 speaker_id는 프론트가
# 립싱크 영상 생성을 시도하지 않고 무한루프 영상+TTS로 폴백한다
# (media_stream.schema.md §2 참고 — 이것도 팀 동의 필요한 제안).
# 재인/Claude(2026-07-17): 2번째 아바타(technical_feasibility) 영상 세트까지
# musetalk_setup_v2.ipynb에서 제스처 포함 검증 완료 - 2명으로 확장.
# 재인/Claude(2026-07-18): persona_c/persona_d 2명 추가 - 4명으로 확장. 이 둘은 실제
# 위원 persona_id가 아니라 CommitteeVideoStage.jsx의 AVATAR_SLOTS와 짝을 이루는
# 얼굴·목소리 전용 식별자다(순서 기반 동적 배정 - 어떤 위원이든 먼저 말하는 순서대로
# 이 슬롯을 빌려쓴다).
# 재인/Claude(2026-07-19): 4명 전원 제스처 영상(_1/_2)까지 준비 완료 - 프론트가 매
# 발화마다 gesture_index(0~2)를 직전 값 제외 랜덤으로 골라 보낸다(CommitteeVideoStage.jsx
# pickGestureIndex 참고). 이 중계 라우터는 요청 JSON을 그대로 업스트림에 전달만 하므로
# gesture_index를 포함해 별도 처리 불필요.
AVAILABLE_SPEAKER_IDS = ["business_strategy", "technical_feasibility", "persona_c", "persona_d"]


@router.get("/available-speakers")
async def available_speakers():
    return {"speaker_ids": AVAILABLE_SPEAKER_IDS}


@router.websocket("/stream")
async def media_stream(client_ws: WebSocket):
    await client_ws.accept()
    print("[media] 클라이언트 연결 수락", flush=True)

    if not settings.MEDIA_SERVICE_WS_URL:
        print("[media] MEDIA_SERVICE_WS_URL 미설정 - 중단", flush=True)
        await client_ws.send_json({"type": "error", "message": "MEDIA_SERVICE_WS_URL이 설정되지 않았습니다"})
        await client_ws.close()
        return

    # Colab 등에서 받은 주소는 보통 https://라서, websockets 라이브러리가 요구하는
    # ws(s):// 스킴으로 바꿔줘야 한다 (web_test_chat.html의 JS 쪽은 이 변환을 프론트에서
    # 직접 했었는데, 이 파이썬 중계 코드에는 빠뜨렸었다 - 그래서 연결 자체가 실패했음).
    upstream_base = settings.MEDIA_SERVICE_WS_URL.rstrip("/")
    if upstream_base.startswith("https://"):
        upstream_base = "wss://" + upstream_base[len("https://"):]
    elif upstream_base.startswith("http://"):
        upstream_base = "ws://" + upstream_base[len("http://"):]
    upstream_url = upstream_base + "/generate-stream"
    print(f"[media] 업스트림 연결 시도: {upstream_url}", flush=True)

    try:
        # 재인/Claude(2026-07-19): ping_interval=None으로 자동 핑퐁 keepalive를 껐다 -
        # 원래는 20초마다 핑을 보내고 응답 없으면 연결을 끊는데, 코랩은 GIL 특성상
        # GPU 추론(스레드)이 도는 동안 이벤트 루프가 핑에 응답할 틈을 못 얻는 경우가
        # 실제로 있었다(위원 여러 명이 겹쳐서 코랩이 바빠질수록 심해짐). 이 "바쁨"을
        # "죽음"으로 오판해서 아직 발화 중인 위원의 연결을 강제로 끊어버리는 버그를
        # 실측 확인했다(발화 20~30초 넘는 위원에서 재현). 어차피 우리는 실제 데이터
        # (영상 프레임/status/tts_end/done 메시지)가 계속 오는지로 연결 상태를 판단할
        # 수 있어서 별도의 핑퐁 생존 확인이 필요 없다 - 진짜 연결이 끊기면(터널 끊김,
        # 코랩 세션 종료 등) 데이터 자체가 안 오거나 TCP 레벨에서 결국 예외가 나서
        # 여전히 감지된다.
        async with websockets.connect(upstream_url, max_size=None, ping_interval=None) as upstream_ws:
            print("[media] 업스트림(Colab) 연결 성공", flush=True)
            # 1. 프론트가 보낸 요청(mediaLine)을 그대로 MuseTalk 서버로 전달
            request_text = await client_ws.receive_text()
            print(f"[media] 클라이언트 요청 수신, 업스트림으로 전달: {request_text[:200]}", flush=True)
            await upstream_ws.send(request_text)

            # 2. MuseTalk 서버가 보내는 걸 그대로 프론트로 중계 (JSON 상태 메시지 + 영상 바이너리)
            msg_count = 0
            byte_total = 0
            async for message in upstream_ws:
                msg_count += 1
                if isinstance(message, bytes):
                    byte_total += len(message)
                    await client_ws.send_bytes(message)
                else:
                    print(f"[media] 업스트림 JSON 메시지 #{msg_count}: {message[:200]}", flush=True)
                    await client_ws.send_text(message)
            print(f"[media] 중계 루프 종료 - 총 {msg_count}개 메시지, {byte_total} bytes 전달", flush=True)
    except WebSocketDisconnect:
        print("[media] 클라이언트가 먼저 연결을 끊음", flush=True)
    except Exception as e:
        print(f"[media] 예외 발생: {e!r}", flush=True)
        traceback.print_exc()
        try:
            await client_ws.send_json({"type": "error", "message": f"미디어 서버 연결 실패: {e}"})
        except Exception:
            pass
    finally:
        print("[media] 연결 종료 처리", flush=True)
        try:
            await client_ws.close()
        except Exception:
            pass
