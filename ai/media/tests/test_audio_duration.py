import wave
import struct
import tempfile
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tts"))
from audio_duration import get_wav_duration_seconds, get_audio_duration_seconds  # noqa: E402


def _make_silent_wav(path: Path, seconds: float, rate: int = 16000) -> None:
    n_frames = int(seconds * rate)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(struct.pack("<%dh" % n_frames, *([0] * n_frames)))


def test_get_wav_duration_seconds():
    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "silence.wav"
        _make_silent_wav(wav_path, seconds=2.5)
        assert abs(get_wav_duration_seconds(wav_path) - 2.5) < 1e-6


def test_get_audio_duration_seconds_dispatches_wav():
    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "silence.wav"
        _make_silent_wav(wav_path, seconds=1.0)
        assert abs(get_audio_duration_seconds(wav_path) - 1.0) < 1e-6


if __name__ == "__main__":
    test_get_wav_duration_seconds()
    test_get_audio_duration_seconds_dispatches_wav()
    print("모든 테스트 통과")
