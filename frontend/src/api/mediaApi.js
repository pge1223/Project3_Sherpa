import { API_BASE_URL } from './client'

// 재인/Claude (2026-07-16): 위원 발언 영상(TTS+MuseTalk 립싱크) 스트리밍용 API 클라이언트.
// 통신 규격: contracts/schemas/media_stream.schema.md (DRAFT, 윤한 확인 필요)
// 사용하는 곳: frontend/src/components/meeting/CommitteeVideoStage.jsx

// 아바타 영상이 실제로 준비된 speaker_id 목록을 물어본다
// (백엔드: backend/app/api/routes/media.py의 AVAILABLE_SPEAKER_IDS).
export async function getAvailableSpeakers() {
  const res = await fetch(`${API_BASE_URL}/media/available-speakers`)
  const data = await res.json()
  if (!res.ok) {
    throw new Error(data.detail || '사용 가능한 위원 목록을 불러오지 못했습니다.')
  }
  return data.speaker_ids
}

// 백엔드의 /media/stream에 WebSocket 연결을 연다. 백엔드가 내부적으로
// MuseTalk 서버(Colab)에 다시 연결해 그대로 중계해준다 - 프론트는 Colab
// 주소를 몰라도 됨.
export function openMediaStreamSocket() {
  const wsUrl = API_BASE_URL.replace(/^https:/, 'wss:').replace(/^http:/, 'ws:') + '/media/stream'
  const ws = new WebSocket(wsUrl)
  ws.binaryType = 'arraybuffer'
  return ws
}
