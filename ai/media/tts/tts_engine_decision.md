# TTS 엔진 선정 (3단계 — TTS 연동)

## 비교

| 엔진 | 비용 | API 키/가입 | 한국어 품질 | 비고 |
|---|---|---|---|---|
| edge-tts (Microsoft Edge TTS 비공식 래퍼) | 무료, 무제한 | 불필요 | 양호 | 비공식 API라 MS가 내부 구조를 바꾸면 깨질 수 있음 |
| **OpenAI TTS (`gpt-4o-mini-tts`)** | 분당 약 $0.015 (텍스트 $0.60/100만 토큰 + 오디오 $12/100만 토큰) | 필요, **단 프로젝트가 이미 OpenAI API를 LLM(위원회 로직)용으로 쓰고 있어 별도 계정 불필요** | edge-tts보다 우수 (재인 직접 사용 경험 기준) | 스타일 지시(steerable) 프롬프트로 톤 조절 가능, 13개 프리셋 보이스 |
| Google Cloud TTS / Azure Speech | 무료 티어 이후 유료 | 별도 계정 필요 | 우수 | 팀 공유용 계정/결제 설정 부담 |
| Naver Clova Voice | 무료 티어(저작권 표시) 이후 유료 | 별도 계정 필요 | 한국어 특화, 매우 우수 | 실시간 스트리밍 미지원 |
| Typecast | 무료 플랜(제한 있음) | 필요 | 감정·억양 우수 | 무료 플랜 상업적 이용 제한 |

## 결정: **OpenAI TTS (`gpt-4o-mini-tts`) 채택**

**이유:**
- 재인이 실사용해본 결과 **edge-tts보다 한국어 음질이 낫다고 판단**
- 프로젝트가 이미 OpenAI API를 LLM 파이프라인(위원회 리뷰/종합)에 사용 중이라, **같은 API 키를 그대로 재사용** 가능 — 별도 계정/키 관리 부담 없음
- 비용이 분당 약 $0.015로 낮아 프로토타입~데모 단계 사용량에서는 부담 없음
- `gpt-4o-mini-tts`는 스타일 지시(voice instructions)를 지원해서, 위원 A/B의 "차분함 vs 분석적" 톤 차이를 프롬프트로도 보강할 수 있음

**edge-tts 관련 참고:** 노트북(`ai/media/musetalk/colab/musetalk_setup.ipynb`) 7번 단계는 아직 edge-tts로 되어 있음 — OpenAI TTS로 교체 필요 (다음 작업)

## 참고
Sources:
- [GPT-4o mini TTS Model | OpenAI API](https://developers.openai.com/api/docs/models/gpt-4o-mini-tts)
- [gpt-4o-mini-tts: Cheapest TTS API in 2026](https://tokenmix.ai/blog/gpt-4o-mini-tts-cheapest-tts-api-2026)
- [Text to speech | OpenAI API](https://developers.openai.com/api/docs/guides/text-to-speech)
