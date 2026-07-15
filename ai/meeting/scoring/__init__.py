# 작성자: 경이
# 목적: ai/meeting/scoring 패키지 공개 인터페이스. 점수 계산 진입점을 노출한다.
# import: 같은 패키지의 calculator, weights, deductions.

from .calculator import calculate_score
from .deductions import compute_penalties
from .weights import resolve_weights

__all__ = ["calculate_score", "compute_penalties", "resolve_weights"]
