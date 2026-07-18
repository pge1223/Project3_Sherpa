# TTS 엔진 선정 (3단계 — TTS 연동)

> **2026-07-18 업데이트:** 아래 "1차 결정"(OpenAI TTS)에서 **ElevenLabs로 최종 변경**했습니다.
> 변경 이유와 비교 근거는 맨 아래 "## 결정 변경(2026-07-18)" 섹션 참고 — 1차 결정 내용은
> 왜 처음에 OpenAI를 골랐는지 기록으로 남겨두기 위해 그대로 둡니다.

## 1차 결정 (2026-07-16, 이후 변경됨)

### 비교

| 엔진 | 비용 | API 키/가입 | 한국어 품질 | 비고 |
|---|---|---|---|---|
| edge-tts (Microsoft Edge TTS 비공식 래퍼) | 무료, 무제한 | 불필요 | 양호 | 비공식 API라 MS가 내부 구조를 바꾸면 깨질 수 있음 |
| **OpenAI TTS (`gpt-4o-mini-tts`)** | 분당 약 $0.015 (텍스트 $0.60/100만 토큰 + 오디오 $12/100만 토큰) | 필요, **단 프로젝트가 이미 OpenAI API를 LLM(위원회 로직)용으로 쓰고 있어 별도 계정 불필요** | edge-tts보다 우수 (재인 직접 사용 경험 기준) | 스타일 지시(steerable) 프롬프트로 톤 조절 가능, 13개 프리셋 보이스 |
| Google Cloud TTS / Azure Speech | 무료 티어 이후 유료 | 별도 계정 필요 | 우수 | 팀 공유용 계정/결제 설정 부담 |
| Naver Clova Voice | 무료 티어(저작권 표시) 이후 유료 | 별도 계정 필요 | 한국어 특화, 매우 우수 | 실시간 스트리밍 미지원 |
| Typecast | 무료 플랜(제한 있음) | 필요 | 감정·억양 우수 | 무료 플랜 상업적 이용 제한 |

### 결정: **OpenAI TTS (`gpt-4o-mini-tts`) 채택**

**이유:**
- 재인이 실사용해본 결과 **edge-tts보다 한국어 음질이 낫다고 판단**
- 프로젝트가 이미 OpenAI API를 LLM 파이프라인(위원회 리뷰/종합)에 사용 중이라, **같은 API 키를 그대로 재사용** 가능 — 별도 계정/키 관리 부담 없음
- 비용이 분당 약 $0.015로 낮아 프로토타입~데모 단계 사용량에서는 부담 없음
- `gpt-4o-mini-tts`는 스타일 지시(voice instructions)를 지원해서, 위원 A/B의 "차분함 vs 분석적" 톤 차이를 프롬프트로도 보강할 수 있음

**edge-tts 관련 참고:** 노트북(`ai/media/musetalk/colab/musetalk_setup.ipynb`) 7번 단계는 아직 edge-tts로 되어 있음 — OpenAI TTS로 교체 필요 (다음 작업)

### 참고
Sources:
- [GPT-4o mini TTS Model | OpenAI API](https://developers.openai.com/api/docs/models/gpt-4o-mini-tts)
- [gpt-4o-mini-tts: Cheapest TTS API in 2026](https://tokenmix.ai/blog/gpt-4o-mini-tts-cheapest-tts-api-2026)
- [Text to speech | OpenAI API](https://developers.openai.com/api/docs/guides/text-to-speech)

## 결정 변경(2026-07-18): **ElevenLabs(`eleven_multilingual_v2`)로 전환**

### 계기
"TTS 생성 속도를 줄이고 싶다"는 목적으로 로컬 모델(Zonos-v0.1, 후속작 ZONOS2)을 다시 검토했으나,
Zonos-v0.1은 한국어가 공식 지원 언어가 아니었고(공식 5개 언어: 영/일/중/불/독), ZONOS2는 한국어를
공식 지원하지만 VRAM 요구량이 늘고(6GB→16GB 권장) 실측 생성 시간도 개선을 확신할 수 없어 방향을
ElevenLabs로 틀었다. (Zonos 관련 상세 진단은 `docs/devlogs/lji-devlog.md` 2026-07-17~18 참고)

### 비교 (추가)

| 엔진 | 비용 | 속도(순수 TTS, 짧은/중간/긴 문장 평균) | 한국어 품질 | 비고 |
|---|---|---|---|---|
| ElevenLabs (`eleven_multilingual_v2`) | Creator 플랜 월 $22(첫달 $11), 월 22만자 | OpenAI 대비 **1.5~2배 빠름** | 실제 립싱크까지 붙여서 청취 확인, 만족 | Voice Library(수백 개 목소리) API 사용은 Creator 플랜부터 |
| ElevenLabs (`eleven_flash_v2_5`) | 위와 동일 플랜 | OpenAI 대비 **4~7.5배 빠름** | 음질이 조금씩 깨진다는 청취 피드백으로 기각 | 실시간 음성봇용으로 설계된 저지연 모델이라 품질 트레이드오프 있음 |
| Zonos-v0.1 | 무료(자체 GPU) | 실측 왜곡 있었음(GPU 디바이스 버그로 CPU 폴백 시 11~12분/문장) | 한국어 비공식 지원이라 불확실 | 통합 중 라이브러리 버그 다수(torchcodec 의존성, GPU/CPU 디바이스 mismatch) — 보류 |
| ZONOS2 | 무료(자체 GPU, VRAM 16GB+ 권장) | 웜업 이후 정상, 첫 호출만 워밍업으로 왜곡(46초→ 이후 6~13초대) | 한국어 공식 지원(Tier 2), 단 텍스트 정규화 실패 사례 실측 확인 | MuseTalk 없이 TTS만 단독 검증(`ai/media/musetalk/colab/zonos2_tts_only_test.ipynb`) |

### 결정: **ElevenLabs, 모델은 `eleven_multilingual_v2`**

**이유:**
- OpenAI 대비 순수 TTS 속도가 확실히 빠름(1.5~2배) — 다만 실측 결과 **전체 체감 속도의 진짜 병목은 TTS가 아니라 MuseTalk 프레임 생성 자체**(전체 소요의 80%+)였다는 것도 같이 확인됨. TTS 교체만으로 큰 속도 개선을 기대하긴 어렵지만, 품질이 만족스럽고 어차피 개선되는 부분이라 채택
- `eleven_flash_v2_5`(4~7.5배 더 빠름)가 있었지만 실제 립싱크 붙여서 들어보니 음질이 조금씩 깨져서 기각 — 속도보다 품질 우선
- Zonos 계열은 로컬/무료라는 장점은 있지만 라이브러리 자체 버그가 많고(디바이스 mismatch, torchcodec 의존성) 한국어 지원 신뢰도가 낮아 채택 안 함 — 완전히 접은 건 아니고 보류 상태
- 위원 아바타가 2명 → 4명으로 늘어나면서 보이스도 4개 필요 — Voice Library(Kelee K, Theo, Gihong, Han)에서 선택. 위원 B는 원래 Yohan Koo였다가 청취 피드백으로 Theo로 재변경

**비용 관련 참고:** OpenAI TTS와 달리 별도 유료 구독(월 $22, Creator 플랜)이 필요 — 팀 공유 계정이 아니라 재인 개인 결제로 우선 진행. 사용량이 늘면 플랜 상향 또는 팀 예산 논의 필요할 수 있음.

### 참고
Sources:
- [ZONOS2: Real-time TTS with High-Fidelity Voice Cloning](https://www.zyphra.com/our-work/zonos2)
- [GitHub - Zyphra/Zonos (v0.1)](https://github.com/Zyphra/Zonos)
- [GitHub - Zyphra/ZONOS2](https://github.com/Zyphra/ZONOS2)
- [ElevenAPI Pricing](https://elevenlabs.io/pricing/api)
- [Voice Library | ElevenLabs Documentation](https://elevenlabs.io/docs/eleven-creative/voices/voice-library)
