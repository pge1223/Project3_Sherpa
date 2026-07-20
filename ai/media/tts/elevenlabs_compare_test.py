# 재인/Claude(2026-07-18): ElevenLabs TTS 속도/음질 비교 테스트 - MuseTalk 없이 TTS만 확인.
# musetalk_setup_v2.ipynb의 Zonos 실험과 같은 3개 한국어 문장(짧은/중간/긴)으로 비교해서
# 결과를 서로 견줄 수 있게 했다. 실행: `python ai/media/tts/elevenlabs_compare_test.py`
# (review-board conda 환경, ai/media/tts/.env에 ELEVENLABS_API_KEY 필요 - Creator 플랜 이상)
import json
import os
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))

# .env 직접 파싱 (python-dotenv 의존성 추가 안 하려고 - 이 스크립트 하나만 쓰는 값이라 간단히)
with open(os.path.join(HERE, ".env"), encoding="utf-8") as f:
    for line in f:
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            os.environ.setdefault(k, v)

API_KEY = os.environ["ELEVENLABS_API_KEY"]

# 위원 A/B에 배정한 한국어 보이스 (Voice Library, Creator 플랜부터 API 사용 가능)
VOICES = {
    "A_KeleeK": "5DWGv3VDkihNUcbvaonB",  # Kelee K - Seoul Narrator (여성)
    "B_YohanKoo": "4JJwo477JUAx3HV0T7n7",  # Yohan Koo - Encouraging, Clear and Airy (남성)
}

# 품질 우선(multilingual_v2) vs 속도 우선(flash_v2_5) 모델 둘 다 비교
MODELS = ["eleven_multilingual_v2", "eleven_flash_v2_5"]

# Zonos 테스트(musetalk_setup_v2.ipynb 14번 섹션)와 동일한 문장 - 결과를 서로 비교하기 위함
TEST_SENTENCES = [
    ("short", "안녕하세요."),
    ("medium", "이번 사업계획서는 시장 진입 전략이 탄탄하지만, 수익 모델은 좀 더 구체화가 필요해 보입니다."),
    (
        "long",
        "제출하신 문서를 검토한 결과, 아이디어의 참신성과 문제 정의의 독창성은 높이 평가하지만, "
        "실행 계획에 필요한 구체적인 일정과 예산, 인력 배치에 대한 근거가 부족하여 추가 보완이 "
        "필요하다고 판단됩니다.",
    ),
]

OUT_DIR = os.path.join(HERE, "elevenlabs_out")
os.makedirs(OUT_DIR, exist_ok=True)


def generate(voice_id, model_id, text):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    body = json.dumps({
        "text": text,
        "model_id": model_id,
        # Creator 플랜부터 192kbps 지원 - 무료 플랜 기본값(낮은 비트레이트)보다 음질 비교에 유리
        "output_format": "mp3_44100_192",
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"xi-api-key": API_KEY, "Content-Type": "application/json"},
    )
    t0 = time.time()
    with urllib.request.urlopen(req) as resp:
        audio = resp.read()
    return audio, time.time() - t0


results = []
for voice_name, voice_id in VOICES.items():
    for model_id in MODELS:
        for sent_name, text in TEST_SENTENCES:
            try:
                audio, elapsed = generate(voice_id, model_id, text)
            except urllib.error.HTTPError as e:
                print(f"[{voice_name}/{model_id}/{sent_name}] 실패: {e.code} {e.read().decode('utf-8')}")
                continue
            out_path = os.path.join(OUT_DIR, f"{voice_name}_{model_id}_{sent_name}.mp3")
            with open(out_path, "wb") as f:
                f.write(audio)
            print(
                f"[{voice_name}/{model_id}/{sent_name}] 글자수={len(text)} "
                f"소요={elapsed:.2f}초 크기={len(audio)}bytes -> {out_path}"
            )
            results.append((voice_name, model_id, sent_name, len(text), elapsed))

print("\n=== 요약 (모델별 평균 소요시간) ===")
for model_id in MODELS:
    times = [r[4] for r in results if r[1] == model_id]
    if times:
        print(f"{model_id}: 평균 {sum(times)/len(times):.2f}초 (n={len(times)})")
