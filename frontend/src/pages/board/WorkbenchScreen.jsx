import { useEffect, useMemo, useState } from 'react'
import { AlertCircle, Lightbulb, MessageSquare, Sparkles } from 'lucide-react'
import { getDocuments, getDocumentPreview } from '../../api/documentApi'
import { getQuoteMatches } from '../../api/workbenchApi'
import { getProjectReport } from '../../api/projectApi'

// 재인/Claude(2026-07-21): docs/REVIEW_BOARD_서비스_방향성_정리_20260720.md의
// "5. 핵심 UI: 시각적 인터랙티브 워크벤치" 1차 구현.
//
// 데이터 출처:
// - 기획서 원문: 기존 DOC-006 문서 미리보기 엔드포인트(parsed_text)를 그대로 가져다 씀
//   (ReviewBoardPrototype.jsx의 UploadAndAnalyzeScreen이 올린 target 문서를
//   getDocuments()로 다시 찾아서 preview 호출).
// - 위원 피드백(issues/suggestions): UploadAndAnalyzeScreen이 분석 끝나고
//   sessionStorage에 저장해둔 review_output(JSON, MentorFeedbackChatPage.jsx가 쓰던
//   것과 동일한 캐시 키)을 그대로 읽는다.
//
// 하이라이트 위치: 위원이 애초에 인용한 evidence.chunk_id로 벡터DB에서 청크 원문을
// ID 직접 조회한다(backend/app/api/routes/workbench.py, 완전히 새 파일 - AI 재호출
// 없이 항상 원문 그대로 반환). GPT에게 원문을 다시 찾아달라고 재질문하는 방식도
// 만들어서 비교해봤으나, 청크 조회 쪽이 AI 호출 없이도 항상 정확해 이 방식만 남겼다.
// evidence_ids가 criterion(평가기준) 단위로만 달려 있어(issue/suggestion 문장 하나하나가
// 아님), 한 기준 아래 모든 항목이 같은 청크를 하이라이트로 공유한다.
//
// 아바타 연동은 아직 1차 버전이 아님 - 오른쪽엔 자리만 잡아두고, 실제 스트리밍은
// ai/media/musetalk/committee_video_streaming_architecture.md의 하위 배관을 재사용해서
// 다음 단계에서 붙인다.

// review_output.evidence는 evidence_id -> {chunk_id, source_type, ...} 배열이다.
// rubric_score.evidence_ids(criterion 단위)에서 "submission"(기획서 본문, 공고문/criteria
// 아님) 소스의 첫 evidence를 골라 그 chunk_id를 이 criterion의 모든 issue/suggestion에 붙인다.
function buildEvidenceChunkMap(reviewOutput) {
  const byId = new Map()
  for (const ev of reviewOutput?.evidence || []) {
    byId.set(ev.evidence_id, ev)
  }
  return byId
}

function firstSubmissionChunkId(evidenceIds, evidenceById) {
  for (const evId of evidenceIds || []) {
    const ev = evidenceById.get(evId)
    if (ev && (ev.source_type === 'submission' || !ev.source_type) && ev.chunk_id) {
      return ev.chunk_id
    }
  }
  return null
}

function extractFeedbackItems(reviewOutput) {
  if (!reviewOutput) return []
  const evidenceById = buildEvidenceChunkMap(reviewOutput)
  const items = []
  for (const reviewer of reviewOutput.reviewer_results || []) {
    for (const rs of reviewer.rubric_scores || []) {
      const chunkId = firstSubmissionChunkId(rs.evidence_ids, evidenceById)
      const kinds = [
        ['issue', rs.issues || []],
        ['suggestion', rs.suggestions || []],
      ]
      for (const [kind, texts] of kinds) {
        for (const text of texts) {
          items.push({
            id: `${reviewer.persona_id}-${rs.criterion_id}-${kind}-${items.length}`,
            kind,
            text,
            criterionName: rs.criterion_name,
            reviewerName: reviewer.persona_name || reviewer.role,
            personaId: reviewer.persona_id,
            judgment: rs.judgment,
            chunkId,
          })
        }
      }
    }
  }
  return items
}

// 원문(text)을 quoteMatches(백엔드 /workbench/{id}/quotes 응답) 위치 기준으로 쪼갠다 -
// 매칭된 구간은 { highlighted: true, feedbackId }를, 나머지는 일반 텍스트 구간을
// 반환한다. 겹치는 인용은 먼저 나온 것이 이긴다.
function buildHighlightSegments(text, quoteMatches, feedbackById) {
  if (!text || !quoteMatches) return []

  const spans = [] // { start, end, feedbackId, kind }
  for (const match of quoteMatches) {
    const quote = (match.quote || '').trim()
    if (!quote) continue
    const idx = text.indexOf(quote)
    if (idx === -1) continue
    const item = feedbackById.get(match.id)
    spans.push({ start: idx, end: idx + quote.length, feedbackId: match.id, kind: item?.kind })
  }
  spans.sort((a, b) => a.start - b.start)

  const cleanSpans = []
  let cursor = 0
  for (const span of spans) {
    if (span.start < cursor) continue
    cleanSpans.push(span)
    cursor = span.end
  }

  const segments = []
  let pos = 0
  for (const span of cleanSpans) {
    if (span.start > pos) segments.push({ text: text.slice(pos, span.start), highlighted: false })
    segments.push({
      text: text.slice(span.start, span.end),
      highlighted: true,
      feedbackId: span.feedbackId,
      kind: span.kind,
    })
    pos = span.end
  }
  if (pos < text.length) segments.push({ text: text.slice(pos), highlighted: false })

  return segments
}

export default function WorkbenchScreen({ projectId }) {
  const [docText, setDocText] = useState(null)
  const [docError, setDocError] = useState('')
  const [reviewOutput, setReviewOutput] = useState(null)
  const [selectedFeedbackId, setSelectedFeedbackId] = useState(null)

  const [quoteMatches, setQuoteMatches] = useState(null)
  const [matchingLoading, setMatchingLoading] = useState(false)
  const [matchingError, setMatchingError] = useState('')

  useEffect(() => {
    if (!projectId) return
    let cancelled = false
    ;(async () => {
      try {
        const docs = await getDocuments(projectId)
        const target = docs.find((d) => (d.document_role || 'target') === 'target')
        if (!target) {
          if (!cancelled) setDocError('업로드된 기획서를 찾지 못했습니다.')
          return
        }
        const preview = await getDocumentPreview(projectId, target.id)
        if (!cancelled) setDocText(preview.parsed_text || '')
      } catch (err) {
        if (!cancelled) setDocError(err.message)
      }
    })()
    return () => { cancelled = true }
  }, [projectId])

  // 가은/Claude(2026-07-21): 실측 제보 — "내 프로젝트"에서 분석이 이미 끝난 프로젝트로
  // 이어서 들어오면(sessionStorage가 이번 세션엔 없는 새 탭/재접속) 워크벤치가 빈 화면으로
  // 보였다. sessionStorage 캐시가 없으면 저장된 회의 결과(RPT-001 /report)를 대신 불러온다.
  useEffect(() => {
    if (!projectId) return
    const cached = sessionStorage.getItem(`analysis:${projectId}`)
    if (cached) {
      try {
        setReviewOutput(JSON.parse(cached))
        return
      } catch (e) {
        console.error('[WorkbenchScreen] 분석 결과 파싱 실패', e)
      }
    }
    let cancelled = false
    getProjectReport(projectId)
      .then((report) => { if (!cancelled) setReviewOutput(report) })
      .catch((err) => { if (!cancelled) console.error('[WorkbenchScreen] 결과 조회 실패', err) })
    return () => { cancelled = true }
  }, [projectId])

  const feedbackItems = useMemo(() => extractFeedbackItems(reviewOutput), [reviewOutput])
  const feedbackById = useMemo(() => new Map(feedbackItems.map((f) => [f.id, f])), [feedbackItems])

  // 재인/Claude(2026-07-21): 워크벤치 진입 시(원문+피드백이 둘 다 준비되면) 자동으로
  // 인용 조회를 호출한다 - 사용자가 따로 버튼을 안 눌러도 된다. 로딩 중엔 기획서
  // 패널에만 로딩 표시를 하고(아바타 쪽은 나중에 붙어도 계속 idle 루프가 돌아야 하므로
  // 전체 화면을 막지 않는다), 끝나면 하이라이트가 나타난다. chunkId가 없는 항목(evidence가
  // criteria/notice뿐이거나 없음)은 애초에 요청에서 뺀다 - 하이라이트가 없을 뿐 다른
  // 항목 조회에는 영향 없다.
  useEffect(() => {
    if (docText === null || feedbackItems.length === 0) return
    const lookups = feedbackItems.filter((f) => f.chunkId)
    if (lookups.length === 0) return
    let cancelled = false
    setMatchingLoading(true)
    setMatchingError('')
    getQuoteMatches(projectId, lookups)
      .then((matches) => { if (!cancelled) setQuoteMatches(matches) })
      .catch((err) => { if (!cancelled) setMatchingError(err.message) })
      .finally(() => { if (!cancelled) setMatchingLoading(false) })
    return () => { cancelled = true }
    // feedbackItems는 reviewOutput이 바뀔 때만 내용이 바뀌므로 reviewOutput을 의존성으로 둔다
    // (매 렌더마다 새 배열 참조가 생겨 무한 재호출되는 것을 방지).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, docText, reviewOutput])

  const segments = useMemo(
    () => buildHighlightSegments(docText, quoteMatches, feedbackById),
    [docText, quoteMatches, feedbackById],
  )

  const selectedFeedback = feedbackItems.find((f) => f.id === selectedFeedbackId) || null

  return (
    <div style={{ display: 'flex', gap: 20, height: 'calc(100vh - 64px)' }}>
      {/* 중앙: 기획서 원문 + 하이라이트 */}
      <div
        className="card glass"
        style={{ flex: 2, minWidth: 0, overflowY: 'auto', padding: 28, lineHeight: 1.8, fontSize: 14.5, position: 'relative' }}
      >
        <div className="badge coral mono" style={{ marginBottom: 14 }}>기획서 원문</div>
        {docError && <p style={{ color: 'var(--coral)', fontSize: 13 }}>{docError}</p>}
        {matchingError && <p style={{ color: 'var(--coral)', fontSize: 13 }}>인용 조회 실패: {matchingError}</p>}
        {!docError && docText === null && <p style={{ color: 'var(--text-2)', fontSize: 13 }}>불러오는 중...</p>}

        {docText !== null && matchingLoading && (
          <div style={{
            position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: 'rgba(250,248,244,0.85)', backdropFilter: 'blur(2px)', fontSize: 13, color: 'var(--text-1)',
          }}>
            AI 위원이 기획서를 짚어보는 중...
          </div>
        )}

        {docText !== null && (
          <div style={{ whiteSpace: 'pre-wrap' }}>
            {segments.length === 0 && !matchingLoading
              ? docText
              : segments.map((seg, i) =>
                seg.highlighted ? (
                  <mark
                    key={i}
                    onClick={() => setSelectedFeedbackId(seg.feedbackId)}
                    style={{
                      cursor: 'pointer',
                      padding: '1px 2px',
                      borderRadius: 3,
                      background: seg.feedbackId === selectedFeedbackId
                        ? 'var(--purple-dim)'
                        : seg.kind === 'issue' ? 'var(--coral-dim)' : 'var(--green-dim)',
                      outline: seg.feedbackId === selectedFeedbackId ? '2px solid var(--purple)' : 'none',
                    }}
                  >
                    {seg.text}
                  </mark>
                ) : (
                  <span key={i}>{seg.text}</span>
                ),
              )}
          </div>
        )}
      </div>

      {/* 오른쪽: 아바타(자리만) + 선택한 피드백 상세 */}
      <div style={{ flex: 1, minWidth: 280, display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div
          className="card glass"
          style={{
            aspectRatio: '9 / 12',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--text-2)',
            fontSize: 13,
          }}
        >
          {/* TODO(재인): committee_video_streaming_architecture.md 5장 참고해서
              위원 1명짜리 스트리밍 재생(WS+MSE 하위 배관)을 여기 연결 - 기획서
              패널만 로딩 표시되는 동안에도 이 자리는 계속 idle 루프가 돌아야 함 */}
          아바타 D 자리 (연동 예정)
        </div>

        <div className="card glass" style={{ flex: 1, overflowY: 'auto', padding: 18 }}>
          {!selectedFeedback && (
            <div style={{ color: 'var(--text-2)', fontSize: 13, display: 'flex', alignItems: 'center', gap: 8 }}>
              <MessageSquare size={16} /> 원문의 하이라이트를 클릭하면 상세 코멘트가 여기 표시됩니다.
            </div>
          )}
          {selectedFeedback && (
            <div>
              <div className="badge mono" style={{
                marginBottom: 10,
                background: selectedFeedback.kind === 'issue' ? 'var(--coral-dim)' : 'var(--green-dim)',
                color: selectedFeedback.kind === 'issue' ? 'var(--coral)' : 'var(--green)',
              }}>
                {selectedFeedback.kind === 'issue' ? <AlertCircle size={12} /> : <Lightbulb size={12} />}
                {selectedFeedback.kind === 'issue' ? '지적사항' : '제안'} · {selectedFeedback.criterionName}
              </div>
              <p style={{ fontSize: 13.5, lineHeight: 1.6, marginBottom: 12 }}>{selectedFeedback.text}</p>
              <div style={{ fontSize: 11.5, color: 'var(--text-2)', display: 'flex', alignItems: 'center', gap: 6 }}>
                <Sparkles size={12} /> {selectedFeedback.reviewerName}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
