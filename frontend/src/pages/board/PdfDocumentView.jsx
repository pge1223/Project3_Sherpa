import { useEffect, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import * as pdfjsLib from 'pdfjs-dist'
import { TextLayer } from 'pdfjs-dist'
import 'pdfjs-dist/web/pdf_viewer.css'

// 재인/Claude(2026-07-21): "AI 피드백" 워크벤치가 기획서를 워드/한글 원본과 완전히 같은
// 페이지 모습으로 보여주기 위해 추가 - 서버가 LibreOffice로 만들어준 PDF(GET
// /documents/{project_id}/{document_id}/preview-pdf)를 pdf.js로 그대로 그린다.
// 페이지마다 <canvas>(눈에 보이는 렌더링) + pdf.js의 textLayer(투명하지만 실제 글자가
// 정확한 위치에 겹쳐 있는 레이어, 원래는 텍스트 선택/복사용)를 같이 만들고, 하이라이트는
// 이 textLayer의 span들 중 인용문과 겹치는 것에 배경색을 입히는 방식으로 한다 - 이번엔
// 문자 단위가 아니라 pdf.js가 나눠준 "텍스트 조각(item)" 단위로 겹치는 걸 통째로
// 칠한다(HTML 버전처럼 글자 하나하나 자르지 않음 - PDF 텍스트 레이어는 절대좌표로
// 배치된 span이라 임의로 쪼개면 레이아웃이 깨질 수 있어서, item 단위가 안전하다).
pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).href

const PAGE_SCALE = 1.4

// 원문 청크 텍스트와 pdf.js가 뽑아내는 텍스트는 글자 하나하나가 정확히 안 맞는다
// (재인/Claude 2026-07-21, 실측 두 가지 원인 확인):
// 1) PDF는 한글<->숫자/영문처럼 폰트가 바뀌는 지점마다 조각(item)이 갈라지는데, 그
//    경계에 원문엔 없던 공백이 생기기도 하고(예: "5년간"이 "5 년간"으로) 반대로 줄바꿈
//    지점엔 있어야 할 공백이 없기도 하다.
// 2) 워드의 번호 매기기 목록(자동 글머리 기호)은 python-docx paragraph.text엔 안 잡히지만
//    LibreOffice가 그린 PDF엔 실제 글리프로 렌더링된다(예: 사설 영역(PUA) 문자 U+F0B7).
// 공백만 정규화해서는 이 두 문제를 다 못 잡는다 - 그래서 아예 문자/숫자가 아닌 모든 것
// (공백·구두점·불릿 글자 포함)을 걸러내고, 남은 문자/숫자만 비교한다.
function buildAlnumMap(text) {
  let normalized = ''
  const map = [] // map[i] = normalized[i]에 대응하는 원본 text의 인덱스
  for (let i = 0; i < text.length; i++) {
    const ch = text[i]
    if (!/[\p{L}\p{N}]/u.test(ch)) continue
    normalized += ch
    map.push(i)
  }
  return { normalized, map }
}

// 청크는 최대 800자라 한 페이지 안에 다 안 들어가고 페이지 경계를 넘기도 한다(실측
// 확인 - 예산 항목이 3페이지 끝에서 4페이지로 이어짐). 그래서 페이지별로 따로 찾지
// 않고, 로드된 모든 페이지의 텍스트 조각을 하나의 좌표계로 이어붙인 뒤 문서 전체에서
// 한 번에 찾는다. 겹치는 하이라이트는 WorkbenchScreen.jsx와 동일하게 "완전히 같은
// 위치면 묶고, 부분적으로만 겹치면 먼저 온 것만" 규칙을 따른다.
function highlightAllPages(pages, quoteMatches, feedbackById) {
  const globalItems = [] // { pageIndex, itemIndex, start, end } (전체 문서 좌표계 기준)
  let flatText = ''
  for (let pageIndex = 0; pageIndex < pages.length; pageIndex++) {
    const { itemsStr } = pages[pageIndex]
    for (let itemIndex = 0; itemIndex < itemsStr.length; itemIndex++) {
      const s = itemsStr[itemIndex]
      const start = flatText.length
      flatText += s
      globalItems.push({ pageIndex, itemIndex, start, end: start + s.length })
    }
  }
  const { normalized, map } = buildAlnumMap(flatText)

  const spans = []
  for (const match of quoteMatches) {
    const rawQuote = (match.quote || '').trim()
    if (!rawQuote) continue
    const { normalized: normalizedQuote } = buildAlnumMap(rawQuote)
    if (!normalizedQuote) continue
    const nIdx = normalized.indexOf(normalizedQuote)
    if (nIdx === -1) continue
    const start = map[nIdx]
    const end = map[nIdx + normalizedQuote.length - 1] + 1
    const item = feedbackById.get(match.id)
    spans.push({ start, end, feedbackId: match.id, kind: item?.kind })
  }
  spans.sort((a, b) => a.start - b.start)

  const grouped = []
  for (const span of spans) {
    const last = grouped[grouped.length - 1]
    if (last && span.start === last.start && span.end === last.end) {
      last.feedbackIds.push(span.feedbackId)
      continue
    }
    if (last && span.start < last.end) continue
    grouped.push({ start: span.start, end: span.end, feedbackIds: [span.feedbackId], kind: span.kind })
  }

  for (const g of grouped) {
    for (const gi of globalItems) {
      if (gi.start >= g.end || gi.end <= g.start) continue // 안 겹침
      const div = pages[gi.pageIndex].textDivs[gi.itemIndex]
      div.classList.add('wb-pdf-highlight', `wb-pdf-highlight-${g.kind || 'issue'}`)
      const existing = div.dataset.feedbackIds ? div.dataset.feedbackIds.split(',') : []
      div.dataset.feedbackIds = Array.from(new Set([...existing, ...g.feedbackIds])).join(',')
    }
  }
}

export default function PdfDocumentView({ pdfUrl, authHeaders, quoteMatches, feedbackById, selectedFeedbackIds, onSelectFeedback }) {
  const containerRef = useRef(null)
  const pagesRef = useRef([]) // [{ wrap, textDivs, itemsStr }]
  // PDF 로딩(LibreOffice 변환 포함)과 인용문 조회(quotes API, Chroma ID 조회라 훨씬 빠름)는
  // 서로 다른 속도로 끝나는 두 개의 비동기 작업이다. 실측 확인 - quotes가 먼저 끝나면
  // PDF 로딩 effect가 그 시점의 quoteMatches를 클로저로 갖고 있어 이후 quoteMatches가
  // 도착해도 반영이 안 됐다(PDF 로딩 effect는 [pdfUrl]에만 의존해 재실행되지 않으므로).
  // ref로 최신값을 항상 따로 들고 있다가, 둘 중 나중에 끝나는 쪽이 항상 최신값으로
  // highlightAllPages를 호출하게 한다.
  const quoteMatchesRef = useRef(quoteMatches)
  const feedbackByIdRef = useRef(feedbackById)
  useEffect(() => {
    quoteMatchesRef.current = quoteMatches
    feedbackByIdRef.current = feedbackById
  }, [quoteMatches, feedbackById])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  // 재인/Claude(2026-07-21): 실측 제보 — 스크롤로 페이지가 계속 이어지니 정리가 안 된
  // 느낌이라, 워드/한글처럼 한 번에 한 페이지만 보여주고 이전/다음으로 넘기게 바꿨다.
  // 페이지는 처음에 전부 렌더링해두고(재렌더링 없이 빠르게 넘기기 위해) display만 토글한다.
  const [currentPage, setCurrentPage] = useState(1)
  const [numPages, setNumPages] = useState(0)

  useEffect(() => {
    if (!pdfUrl) return
    let cancelled = false
    setLoading(true)
    setError('')

    ;(async () => {
      try {
        const pdf = await pdfjsLib.getDocument({ url: pdfUrl, httpHeaders: authHeaders }).promise
        if (cancelled) return

        const root = containerRef.current
        root.innerHTML = ''
        pagesRef.current = []

        for (let pageNum = 1; pageNum <= pdf.numPages; pageNum++) {
          const page = await pdf.getPage(pageNum)
          const viewport = page.getViewport({ scale: PAGE_SCALE })

          const pageWrap = document.createElement('div')
          pageWrap.className = 'wb-pdf-page'
          pageWrap.style.width = `${viewport.width}px`
          pageWrap.style.height = `${viewport.height}px`

          const canvas = document.createElement('canvas')
          canvas.width = viewport.width
          canvas.height = viewport.height
          pageWrap.appendChild(canvas)

          const textLayerDiv = document.createElement('div')
          textLayerDiv.className = 'textLayer'
          textLayerDiv.style.width = `${viewport.width}px`
          textLayerDiv.style.height = `${viewport.height}px`
          pageWrap.appendChild(textLayerDiv)

          // "선택됨" 표시 전용 레이어 - textLayer 위에 별도로 얹는다. 조각(span)마다
          // 직접 클래스를 칠하면(예전 방식) 조각 경계마다 끊겨 보였는데, 여기서는
          // 선택된 조각들을 줄 단위로 묶어 통짜 사각형을 그려 넣는다(아래 selectedFeedbackIds
          // effect 참고). pointer-events:none이라 클릭은 그대로 밑의 textLayer가 받는다.
          const selectionLayer = document.createElement('div')
          selectionLayer.className = 'wb-pdf-selection-layer'
          pageWrap.appendChild(selectionLayer)

          root.appendChild(pageWrap)

          await page.render({ canvasContext: canvas.getContext('2d'), viewport }).promise
          if (cancelled) return

          const textContent = await page.getTextContent()
          const textLayer = new TextLayer({ textContentSource: textContent, container: textLayerDiv, viewport })
          await textLayer.render()
          if (cancelled) return

          pagesRef.current.push({
            wrap: pageWrap,
            textDivs: textLayer.textDivs,
            itemsStr: textLayer.textContentItemsStr,
            selectionLayer,
          })
        }

        if (!cancelled) {
          pagesRef.current.forEach((p, i) => { p.wrap.style.display = i === 0 ? 'block' : 'none' })
          setNumPages(pdf.numPages)
          setCurrentPage(1)
          if (quoteMatchesRef.current) {
            highlightAllPages(pagesRef.current, quoteMatchesRef.current, feedbackByIdRef.current)
          }
        }
      } catch (err) {
        if (!cancelled) setError(err.message || 'PDF를 불러오지 못했습니다.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()

    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pdfUrl])

  useEffect(() => {
    pagesRef.current.forEach((p, i) => { p.wrap.style.display = i === currentPage - 1 ? 'block' : 'none' })
  }, [currentPage])

  useEffect(() => {
    if (!quoteMatches || pagesRef.current.length === 0) return
    highlightAllPages(pagesRef.current, quoteMatches, feedbackById)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [quoteMatches])

  // 선택된 인용문 조각들을 줄(라인) 단위로 사각형을 그린다 - pdf.js 공식 하이라이트
  // 예제(Nutrient의 "PDF.js text highlight annotations" 가이드)가 쓰는 방식과 동일하게
  // getBoundingClientRect() 기준 실제 화면 좌표를 쓴다. offsetTop/offsetWidth는 pdf.js가
  // 조각마다 폰트 보정용 CSS transform: scale()을 걸어서 실제 화면 위치와 어긋날 수 있다
  // (재인/Claude 2026-07-21 - 이전 버전에서 관련 없는 문단까지 뒤덮는 큰 박스가 그려진
  // 원인으로 추정). 줄 판정도 "top 값이 몇 px 이내면 같은 줄"이 아니라 "세로 범위가
  // 겹치면 같은 줄"로 바꿔서, 글머리 기호(•)처럼 높이가 살짝 다른 조각도 같은 줄로
  // 제대로 묶이게 했다.
  useEffect(() => {
    for (const p of pagesRef.current) {
      if (!p.selectionLayer) continue
      p.selectionLayer.innerHTML = ''
      if (selectedFeedbackIds.length === 0) continue

      const pageRect = p.wrap.getBoundingClientRect()
      const matched = []
      for (const div of p.textDivs) {
        if (!div.dataset.feedbackIds) continue
        const ids = div.dataset.feedbackIds.split(',')
        if (!ids.some((id) => selectedFeedbackIds.includes(id))) continue
        const r = div.getBoundingClientRect()
        if (r.width === 0 || r.height === 0) continue // 공백류(빈 조각)는 제외
        matched.push({
          left: r.left - pageRect.left,
          top: r.top - pageRect.top,
          right: r.right - pageRect.left,
          bottom: r.bottom - pageRect.top,
        })
      }
      if (matched.length === 0) continue
      matched.sort((a, b) => a.top - b.top || a.left - b.left)

      const lines = []
      for (const m of matched) {
        // 세로 범위가 기존 줄과 겹치면 같은 줄로 합친다(top 값만 비교하면 글머리
        // 기호처럼 크기가 다른 조각이 다른 줄로 잘못 분리될 수 있다).
        const line = lines.find((l) => m.top < l.bottom && m.bottom > l.top)
        if (line) {
          line.left = Math.min(line.left, m.left)
          line.top = Math.min(line.top, m.top)
          line.right = Math.max(line.right, m.right)
          line.bottom = Math.max(line.bottom, m.bottom)
        } else {
          lines.push({ ...m })
        }
      }

      for (const line of lines) {
        const el = document.createElement('div')
        el.className = 'wb-pdf-selection-box'
        el.style.left = `${line.left - 3}px`
        el.style.top = `${line.top - 2}px`
        el.style.width = `${line.right - line.left + 6}px`
        el.style.height = `${line.bottom - line.top + 4}px`
        p.selectionLayer.appendChild(el)
      }
    }
  }, [selectedFeedbackIds])

  function handleClick(e) {
    const target = e.target.closest('[data-feedback-ids]')
    if (!target) return
    onSelectFeedback(target.dataset.feedbackIds.split(','))
  }

  return (
    <div>
      {error && <p style={{ color: 'var(--coral)', fontSize: 13 }}>{error}</p>}
      {loading && <p style={{ color: 'var(--text-2)', fontSize: 13 }}>페이지를 불러오는 중...</p>}

      {!loading && numPages > 1 && (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 14, marginBottom: 14 }}>
          <button
            type="button"
            onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
            disabled={currentPage <= 1}
            className="badge mono"
            style={{ border: 'none', cursor: currentPage <= 1 ? 'default' : 'pointer', opacity: currentPage <= 1 ? 0.4 : 1 }}
          >
            <ChevronLeft size={14} />
          </button>
          <span style={{ fontSize: 12.5, color: 'var(--text-2)', fontFamily: 'monospace' }}>
            {currentPage} / {numPages}
          </span>
          <button
            type="button"
            onClick={() => setCurrentPage((p) => Math.min(numPages, p + 1))}
            disabled={currentPage >= numPages}
            className="badge mono"
            style={{ border: 'none', cursor: currentPage >= numPages ? 'default' : 'pointer', opacity: currentPage >= numPages ? 0.4 : 1 }}
          >
            <ChevronRight size={14} />
          </button>
        </div>
      )}

      <div
        ref={containerRef}
        onClick={handleClick}
        style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 24 }}
      />
    </div>
  )
}
