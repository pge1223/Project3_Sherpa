"""
LLM 프롬프트 조립.

라벨별 힌트 문구는 ai/meeting/personas/{competition,government_support,startup}.json의
committee 관점 키워드(창의성·차별성 / 정책목표·공공성·예산집행 / 문제·시장·수익모델·투자준비도)와
어휘를 맞춰, 이후 rubric_mapping이 쓰는 관점과 프롬프트의 판단 기준이 크게 어긋나지 않게 한다.
"""

from __future__ import annotations

_INSTRUCTIONS = """\
너는 사업계획서·기획서 등을 검토받기 위해 업로드된 공고문(또는 문서) 발췌를 보고,
이 문서가 어떤 성격의 공모/지원 절차에 속하는지 분류하는 보조자다.

가능한 라벨은 다음 세 가지뿐이다:
- "competition": 아이디어·작품·디자인 공모전. 창의성/독창성/참신성, 결과물 완성도,
  시상·수상 중심의 절차. 심사위원회가 작품성/차별성/구현 가능성을 평가한다.
- "government_support": 정부·지자체·공공기관의 지원사업 공고. 정책목표 부합성,
  신청 자격·공공성, 예산 편성과 집행계획, 공고문 조항·근거 인용이 핵심이다.
- "startup": 스타트업 사업계획서/IR 심사. 문제-고객-시장-수익모델, 기술 적합성과
  구현·운영 가능성, 성장지표(채널/획득/리텐션), 투자·자금 조달 준비도가 핵심이다.

규칙:
1. 위 세 라벨 중 하나만 고른다. 애매하면 가장 근접한 라벨을 고르되 confidence를
   낮게 준다 — 라벨을 억지로 확정하려 하지 마라.
2. confidence는 0.0~1.0 사이 숫자로, 이 문서가 그 라벨에 속한다고 얼마나 확신하는지
   나타낸다. 문서에 성격을 판단할 단서가 거의 없으면 confidence를 낮게(0.3 이하) 준다.
3. reasoning에는 어떤 문구/단서를 근거로 판단했는지 한국어로 간결하게 설명한다.
4. scores에는 세 라벨 각각에 대해 이 문서가 그 라벨일 가능성을 0.0~1.0으로 준다
   (합이 1일 필요는 없다). 판단 근거가 전혀 없으면 생략해도 된다.

다음 JSON 형식으로만 응답한다(설명 문장, 마크다운 코드블록 없이 JSON만):
{
  "domain": "competition 또는 government_support 또는 startup",
  "confidence": 0.0~1.0 사이 숫자,
  "reasoning": "판단 근거",
  "scores": {"competition": 0.0~1.0, "government_support": 0.0~1.0, "startup": 0.0~1.0}
}

문서 발췌:
"""


def build_classification_prompt(document_text: str) -> str:
    """분류 대상 텍스트로 LLM 프롬프트를 만든다. document_text는 반드시
    공백이 아닌 내용을 가져야 한다 — 빈 문서는 호출자(서비스 계층)가 애초에
    LLM을 호출하지 않고 UNKNOWN을 반환해야 한다."""
    if not document_text or not document_text.strip():
        raise ValueError("document_text가 비어 있으면 프롬프트를 만들 수 없습니다")
    return _INSTRUCTIONS + document_text.strip()
