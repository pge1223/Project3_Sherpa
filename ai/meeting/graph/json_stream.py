# 작성자: 용준/Claude(2026-07-21)
# 목적: 대화형 아이디어 발전 회의(ideation-conversation)에서 LLM이 반환하는 구조화 JSON
#       (예: {"judgment": "...", "question": "..."})을 OpenAI가 토큰을 흘려보내는 즉시,
#       필드명·중괄호 등 내부 구조는 절대 노출하지 않고 지정된 필드의 문자열 값만 실시간
#       델타로 뽑아내기 위한 순수 함수/클래스 모음이다.
#
#       설계 배경(요청 "구조화 JSON 출력 처리" 옵션 A): OpenAI json_object 모드는 완성된
#       전체 응답이 도착해야 json.loads가 성공하므로, 원문 델타를 그대로 화면에 흘리면
#       "{\"judgment\": \"바쁜" 처럼 JSON 문법이 그대로 노출된다. 이 모듈은 raw 텍스트가
#       자라날 때마다(feed) "<field_name>": "..." 패턴을 스캐닝해, 그 문자열 값 안에서
#       "지금까지 안전하게 디코딩 가능한 접두부"만 추출해 이전에 emit한 길이와 비교한
#       델타만 반환한다 — 이스케이프 시퀀스(\n, \", \uXXXX 등)가 청크 경계에서 잘려도
#       다음 feed에서 정확히 이어붙는다.
#
#       이 모듈은 그래프/노드 코드(ideation_conv_nodes.py 등)나 FastAPI를 전혀 참조하지
#       않는 순수 유틸리티다 — backend/app/api/routes/ideation_conversation_preview.py가
#       OpenAI 스트리밍 응답을 이 클래스에 먹여 이벤트를 만든다. 필드가 정확히 이 순서로
#       도착한다는 보장은 없다(LLM이 스키마 순서를 어길 수 있음) — 그런 경우 해당 필드는
#       실시간으로는 못 잡고 최종 파싱 결과에만 반영된다(정확성은 항상 최종
#       json.loads+스키마 검증이 보장하므로, 이 모듈은 "미리 보여주기"를 위한 best-effort
#       계층일 뿐이다).
# import: 표준 라이브러리 re만 사용.

from __future__ import annotations

import re

_ESCAPE_MAP = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}

_KEY_TAIL_RE = re.compile(r"\s*:\s*")


def decode_partial_json_string(raw: str) -> tuple[str, bool, int | None]:
    """JSON 문자열 리터럴의 여는 큰따옴표 "다음" 원문(raw)을 처음부터 스캔해서
    (지금까지 안전하게 디코딩된 문자열, 닫는 큰따옴표까지 도달했는지, 도달했다면 raw에서
    소비한 길이(닫는 " 포함))을 반환한다.

    청크 경계에서 이스케이프 시퀀스가 잘리면(예: raw가 "...\\" 로 끝남) 그 지점 이전까지만
    디코딩하고 closed=False로 반환한다 — 호출부가 다음 feed 이후 raw가 늘어난 상태로 다시
    호출하면 이어서 정확히 디코딩된다."""
    out: list[str] = []
    i = 0
    n = len(raw)
    while i < n:
        ch = raw[i]
        if ch == '"':
            return "".join(out), True, i + 1
        if ch == "\\":
            if i + 1 >= n:
                break  # 이스케이프 시작 문자만 온 상태 — 다음 조각을 기다린다.
            nxt = raw[i + 1]
            if nxt == "u":
                if i + 6 > n:
                    break  # \\uXXXX 전체가 아직 도착하지 않았다.
                hex4 = raw[i + 2 : i + 6]
                try:
                    out.append(chr(int(hex4, 16)))
                except ValueError:
                    pass
                i += 6
                continue
            mapped = _ESCAPE_MAP.get(nxt)
            out.append(mapped if mapped is not None else nxt)
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out), False, None


class JSONFieldStreamer:
    """스트리밍 대상 필드 이름 목록을 받아, raw JSON 텍스트가 점진적으로 도착할 때마다
    각 필드의 문자열 값을 디코딩된 델타 텍스트로 흘려보낸다.

    field_order는 "우선순위 힌트"일 뿐 엄격한 순서 강제가 아니다 — LLM이 optional
    필드(예: 결합 직후가 아닌 일반 질문의 user_selection_summary)를 아예 키째로
    생략하거나(null조차 안 씀) 스키마 순서를 어기는 경우가 실제로 있으므로, 매 feed마다
    "아직 시작하지 않은 필드들 중 raw 텍스트에 가장 먼저(왼쪽에) 등장하는 키"를 찾아
    그것부터 처리한다 — 특정 필드의 키가 끝내 나타나지 않아도 다른 필드들의 스트리밍을
    막지 않는다(이 부분이 이전 버전의 버그였다: 필드가 정확히 이 순서로, 그리고 반드시
    존재해야 한다고 가정했더니 한 필드라도 없으면 전체가 멈췄다).

    feed(chunk)는 (field_name, delta_text) 이벤트 목록을 반환한다. delta_text가 None이면
    "이 필드 값이 방금 완전히 닫혔다"는 표시다(문자열 델타가 아니다) — 호출부가 필드 하나가
    끝난 시점(고정 문구를 덧붙이거나 다음 필드 헤더로 넘어갈 시점)을 정확히 알아야 할 때
    쓴다. 필드 값이 문자열이 아니라 null/숫자/불리언/배열/객체이면 그 필드는 조용히
    건너뛴다(닫힘 이벤트도 발생하지 않는다 — 애초에 텍스트 스트림이 시작된 적이 없으므로)."""

    def __init__(self, field_order: list[str]):
        self._pending: set[str] = set(field_order)
        self._raw = ""
        self._scan_pos = 0
        self._in_value = False
        self._current_field: str | None = None
        self._value_start: int | None = None
        self._decoded_emitted = ""

    def _find_next_field(self) -> tuple[str, int] | None:
        best_field = None
        best_pos = None
        for field in self._pending:
            key_pos = self._raw.find(f'"{field}"', self._scan_pos)
            if key_pos != -1 and (best_pos is None or key_pos < best_pos):
                best_pos = key_pos
                best_field = field
        if best_field is None:
            return None
        return best_field, best_pos

    def feed(self, chunk: str) -> list[tuple[str, str]]:
        if not chunk:
            return []
        self._raw += chunk
        events: list[tuple[str, str]] = []
        while True:
            if not self._in_value:
                if not self._pending:
                    break
                found = self._find_next_field()
                if found is None:
                    break  # 남은 필드 중 어느 것도 아직 raw에 나타나지 않았다.
                field, key_pos = found
                after_key = key_pos + len(f'"{field}"')
                m = _KEY_TAIL_RE.match(self._raw, after_key)
                if not m:
                    break  # 콜론까지 아직 도착하지 않았다 — 다음 feed를 기다린다.
                after_colon = m.end()
                if after_colon >= len(self._raw):
                    break  # 값의 첫 글자까지 아직 도착하지 않았다.
                first_ch = self._raw[after_colon]
                if first_ch == '"':
                    self._current_field = field
                    self._pending.discard(field)
                    self._value_start = after_colon + 1
                    self._in_value = True
                    self._decoded_emitted = ""
                elif first_ch == "n":
                    if self._raw[after_colon : after_colon + 4] == "null":
                        self._pending.discard(field)
                        self._scan_pos = after_colon + 4
                        continue
                    break  # "null" 전체가 아직 다 도착하지 않았다.
                else:
                    # 문자열도 null도 아닌 값 — 스트리밍 대상 필드는 항상 string|null로
                    # 설계돼 있으므로 예상 밖 응답이다. 건너뛴다.
                    self._pending.discard(field)
                    self._scan_pos = after_colon
                    continue
            else:
                raw_value_so_far = self._raw[self._value_start :]
                decoded, closed, consumed = decode_partial_json_string(raw_value_so_far)
                field_name = self._current_field
                if len(decoded) > len(self._decoded_emitted):
                    delta = decoded[len(self._decoded_emitted) :]
                    events.append((field_name, delta))
                    self._decoded_emitted = decoded
                if closed:
                    self._in_value = False
                    self._scan_pos = self._value_start + consumed
                    self._current_field = None
                    # delta=None은 "이 필드 값이 방금 닫혔다"는 표시다 — 호출부가 필드
                    # 하나가 완전히 끝난 시점(예: 고정 문구를 덧붙이거나 다음 필드의 헤더로
                    # 넘어갈 시점)을 정확히 알아야 할 때 이 이벤트를 쓴다.
                    events.append((field_name, None))
                else:
                    break  # 이 필드 값이 아직 안 끝났다 — 다음 feed를 기다린다.
        return events

    def remaining_fields(self) -> set[str]:
        """아직 스트리밍으로 잡지 못한 필드 이름 집합 — 테스트/디버깅용."""
        return set(self._pending)
