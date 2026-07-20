// 가은/Claude(2026-07-18): fetch-url 응답의 text_length가 이 값보다 작으면 "본문을 거의
// 못 찾았다"로 간주해 경고를 띄운다 — 실제 평가기준 공고문은 보통 최소 이 정도 분량은
// 된다. 백엔드가 indexed_empty(청크 0개)로 판단하기 전에도(짧지만 청크는 생기는 애매한
// 경우) 프론트에서 한 번 더 걸러준다.
const _CRITERIA_MIN_TEXT_LENGTH = 300

// 가은/Claude(2026-07-18): url_loader.py의 _UNSUPPORTED_REASON과 같은 문자열 — HWP
// 미지원 경고는 unsupported_attachments가 하나라도 있으면 항상 warnings에 끼어 있어서,
// 이걸 그대로 "본문이 부실하다"는 신호로 썼더니 서울시 규제혁신 공모전(본문에
// 심사기준·배점까지 다 있던 케이스)에서도 "확인 필요"가 잘못 떴다(사용자 실측 지적,
// 2026-07-18) — HWP 경고는 따로 떼어서 다룬다.
const HWP_UNSUPPORTED_WARNING = 'HWP/HWPX 형식은 현재 미지원이며 다운로드/파싱하지 않습니다.'

// 가은/Claude(2026-07-18): 본문 길이만으로는 "심사기준이 이미 본문에 있는지"를 못
// 가른다 — 개인정보보호 공모전(1,112자, 요강 HWP만 언급)과 서울시 규제혁신 공모전
// (4,278자, 배점표까지 명시) 둘 다 300자는 훌쩍 넘어서 길이 기준만으론 둘을 구분 못
// 함. "배점/심사기준" 같은, 한국 공고문에서 심사기준 절에 거의 항상 쓰이는 표현이
// 본문에 있는지로 판단한다.
const CRITERIA_KEYWORDS = ['배점', '심사기준', '심사 기준', '평가기준', '평가 기준', '채점']

// 가은/Claude(2026-07-18): DocumentUploadPage(/projects/new)와 ReviewBoardPrototype(/board)
// 양쪽에서 URL로 가져온 공고문 본문이 "쓸 만한지" 같은 기준으로 판정해야 해서 공용
// 유틸로 뺐다. 색인 자체의 성공/실패/타임아웃은 이 함수가 아니라 호출부의
// pollDocumentIndexing류가 별도로 처리한다 — 이 함수는 "본문이 쓸 만한가"만 본다.
export function assessCriteriaContent(result) {
  const attachmentCount = result.attachments?.length || 0
  const textLength = result.page_content?.text_length ?? 0
  const looksEmpty = attachmentCount === 0 && textLength < _CRITERIA_MIN_TEXT_LENGTH
  const unsupportedLinks = result.unsupported_attachments || []
  const contentWarning = (result.warnings || []).find((w) => w !== HWP_UNSUPPORTED_WARNING)
  const hasCriteriaSignal = CRITERIA_KEYWORDS.some((k) => (result.page_content?.text || '').includes(k))

  let status = 'done'
  // 가은/Claude(2026-07-21): 실측 지적 — "첨부파일 2개 수집 · HWP 1개는 못 읽었어요"가
  // 마치 "2개 중 1개를 못 읽었다"(부분집합)처럼 읽혔다. attachments(자동으로 읽어서 수집
  // 완료한 것)와 unsupported_attachments(HWP라 아예 못 읽은 것)는 서로 다른, 겹치지 않는
  // 별개 목록이다 — "이 외"를 붙여 별도 개수임을 명시한다.
  let meta = attachmentCount > 0 ? `첨부파일 ${attachmentCount}개 자동 수집 완료` : new URL(result.origin_url).hostname

  if (contentWarning) {
    status = 'warning'
    meta = contentWarning
  } else if (unsupportedLinks.length > 0 && !hasCriteriaSignal) {
    status = 'warning'
    meta =
      `이 페이지에 HWP 첨부파일 ${unsupportedLinks.length}개가 있어 자동으로 읽지 못했습니다 — ` +
      '평가기준이 그 안에만 있을 수 있어요. 아래에서 받아 "파일 업로드" 탭으로 직접 올려주세요.'
  } else if (looksEmpty) {
    status = 'warning'
    meta = '이 페이지에서 공고 내용을 거의 찾지 못했습니다 — 실제 공고 상세 페이지 URL이 맞는지 확인해주세요.'
  } else if (unsupportedLinks.length > 0) {
    meta += ` · 이 외 HWP 첨부 ${unsupportedLinks.length}개는 자동으로 못 읽었어요(선택 — 필요하면 아래에서 받아 올리세요)`
  }

  return { status, meta, unsupportedLinks }
}
