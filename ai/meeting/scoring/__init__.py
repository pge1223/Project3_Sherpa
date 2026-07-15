# 작성자: 경이
# 목적: ai/meeting/scoring 패키지 공개 인터페이스. 점수 계산·점수 설명 카드 진입점을 노출한다.
# import: 같은 패키지의 calculator, weights, deductions, explanation.

from .calculator import calculate_score
from .deductions import compute_penalties
from .explanation import build_score_explanation
from .weights import resolve_weights

__all__ = ["build_score_explanation", "calculate_score", "compute_penalties", "resolve_weights"]
