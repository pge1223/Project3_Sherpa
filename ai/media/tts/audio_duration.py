"""오디오 길이(초) 계산 로직 (3단계 — 오디오 길이 계산 로직).

wav는 표준 라이브러리 `wave`만으로 순수 파이썬으로 계산한다.
mp3 등 다른 포맷은 표준 라이브러리로 헤더를 파싱할 수 없어 ffprobe로 대체한다
(GPU 불필요, 시스템에 ffmpeg만 있으면 됨).
"""

import subprocess
import wave
from pathlib import Path


def get_wav_duration_seconds(path: str | Path) -> float:
    with wave.open(str(path), "rb") as f:
        frames = f.getnframes()
        rate = f.getframerate()
        return frames / float(rate)


def get_audio_duration_seconds(path: str | Path) -> float:
    path = Path(path)
    if path.suffix.lower() == ".wav":
        return get_wav_duration_seconds(path)

    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]
    )
    return float(out.decode().strip())


if __name__ == "__main__":
    import sys

    for p in sys.argv[1:]:
        print(f"{p}: {get_audio_duration_seconds(p):.3f}s")
