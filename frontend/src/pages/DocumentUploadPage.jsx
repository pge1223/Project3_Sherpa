import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import DocumentRow from '../components/upload/DocumentRow'
import { isAcceptedDocument, formatFileSize, ACCEPTED_DOCUMENT_EXTENSIONS } from '../utils/file'
import { createProject, getProject } from '../api/projectApi'
import { uploadDocument, fetchUrl, getDocuments } from '../api/documentApi'
import { DOC_TYPE_OPTIONS } from '../utils/docType'
import StepSidebar from '../components/wizard/StepSidebar'

// 가은/Claude(2026-07-16): 백엔드 document.status -> 이 화면의 DocumentRow status로 매핑.
// 인덱싱이 안 끝난 상태('uploaded')는 새로고침 시점엔 이미 끝나 있을 확률이 높지만,
// 혹시 몰라 'embedding'으로 보수적으로 처리한다.
function toRowStatus(backendStatus) {
  if (backendStatus === 'indexed') return 'done'
  // 가은/Claude(2026-07-18): "URL은 가져왔지만(HTTP 200) 색인할 청크가 0개"인 상태 —
  // sotong.go.kr 공고 URL로 실측: 게시판 상세 링크가 잘못돼(파라미터 누락 등) 실제
  // 공고 내용이 아닌 페이지가 와도 fetch 자체는 성공해서 예전엔 그냥 'done'(✓ 완료)으로
  // 표시됐다 — 사용자가 "이렇게 떠서 안 되는지 안내가 있어야 한다"고 지적한 지점.
  // done과 구분되는 warning 배지로 표시한다.
  if (backendStatus === 'indexed_empty') return 'warning'
  if (backendStatus === 'indexing_failed' || backendStatus === 'conversion_failed') return 'error'
  return 'embedding'
}

// 가은/Claude(2026-07-18): fetch-url 응답의 text_length가 이 값보다 작으면 "본문을 거의
// 못 찾았다"로 간주해 경고를 띄운다 — 실제 평가기준 공고문은 보통 최소 이 정도 분량은
// 된다. 백엔드가 indexed_empty(청크 0개)로 판단하기 전에도(짧지만 청크는 생기는 애매한
// 경우) 프론트에서 한 번 더 걸러준다.
const _CRITERIA_MIN_TEXT_LENGTH = 300

function UploadIcon() {
  return (
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#7c4dff" strokeWidth="1.8">
      <path d="M12 16V4M12 4 7 9M12 4l5 5" />
      <path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
    </svg>
  )
}

export default function DocumentUploadPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  // 가은/Claude(2026-07-18): StepSidebar가 projectId 없이 "/projects/null/..."류 경로를
  // 만들던 버그(StepSidebar.jsx 주석 참고) 때문에 ?projectId=null이 실제 쿼리로 들어와
  // ensureProject()가 진짜 프로젝트를 안 만들고 문자열 "null"을 그대로 써버려 업로드가
  // POST /documents/null(500)로 깨지는 걸 실측했다 — 근본 원인(StepSidebar)은 고쳤지만,
  // 이미 공유된 링크나 브라우저 히스토리에 그런 URL이 남아있을 수 있어 여기서도 방어한다.
  const rawProjectId = searchParams.get('projectId')
  const continuingProjectId = rawProjectId && rawProjectId !== 'null' && rawProjectId !== 'undefined' ? rawProjectId : null

  const [criteriaTab, setCriteriaTab] = useState('url')
  const [criteriaUrl, setCriteriaUrl] = useState('')
  const [documents, setDocuments] = useState([])
  const [isDragging, setIsDragging] = useState(false)
  const [isCriteriaDragging, setIsCriteriaDragging] = useState(false)
  const [fileError, setFileError] = useState('')
  const [title, setTitle] = useState('새 프로젝트')
  const [docType, setDocType] = useState(DOC_TYPE_OPTIONS[0].value)
  const [projectId, setProjectId] = useState(continuingProjectId)
  const [criteriaLoading, setCriteriaLoading] = useState(false)
  const [criteriaError, setCriteriaError] = useState('')
  const [analyzing, setAnalyzing] = useState(false)
  const [analyzeError, setAnalyzeError] = useState('')
  const [loadingExisting, setLoadingExisting] = useState(!!continuingProjectId)

  const targetFileInputRef = useRef(null)
  const criteriaFileInputRef = useRef(null)

  // 가은/Claude(2026-07-16): StepSidebar에서 "정보 입력/문서 첨부" 단계로 다시 들어올 때
  // ?projectId=가 있으면(진행 중이던 프로젝트) 새로 만들지 않고 이어서 보여준다 — 제목/문서
  // 유형/이미 업로드된 문서 목록을 그대로 불러온다.
  useEffect(() => {
    if (!continuingProjectId) return
    Promise.all([getProject(continuingProjectId), getDocuments(continuingProjectId)])
      .then(([project, docs]) => {
        setTitle(project.title)
        setDocType(project.doc_type)
        setDocuments(
          docs.map((d) => {
            const status = toRowStatus(d.status)
            const unsupportedLinks = d.unsupported_attachments || []
            let meta = formatFileSize(d.file_size)
            // 가은/Claude(2026-07-18): 재로드 시점엔 본문 원문이 응답에 없어(DocumentResponse가
            // parsed_text를 안 돌려줌) 키워드로 재판정할 수 없다 — 대신 backend status가
            // 'indexed'(=색인된 청크가 실제로 있음)면 본문이 충분했다는 뜻이므로, 그때는
            // HWP를 경고가 아니라 선택적 참고자료로만 보여준다(신규 fetch 로직과 동일 원칙 —
            // 본문이 이미 충분하면 HWP 미확보를 경고로 취급하지 않는다).
            if (status === 'warning') {
              meta = unsupportedLinks.length > 0
                ? `이 페이지에 HWP 첨부파일 ${unsupportedLinks.length}개가 있어 자동으로 읽지 못했습니다 — ` +
                  '평가기준이 그 안에만 있을 수 있어요. 아래에서 받아 "파일 업로드" 탭으로 직접 올려주세요.'
                : (d.source_type === 'url'
                  ? '이 페이지에서 공고 내용을 거의 찾지 못했습니다 — 실제 공고 상세 페이지 URL이 맞는지 확인해주세요.'
                  : meta)
            } else if (unsupportedLinks.length > 0) {
              meta += ` · HWP 첨부 ${unsupportedLinks.length}개는 자동으로 못 읽었어요(선택 — 필요하면 아래에서 받아 올리세요)`
            }
            return {
              id: d.id,
              type: d.source_type === 'url' ? 'url' : 'file',
              name: d.original_filename,
              meta,
              status,
              progress: 100,
              unsupportedLinks,
            }
          }),
        )
      })
      .catch((err) => setAnalyzeError(err.message))
      .finally(() => setLoadingExisting(false))
  }, [continuingProjectId])

  async function ensureProject() {
    if (projectId) return projectId
    const project = await createProject({ title, doc_type: docType })
    setProjectId(project.id)
    return project.id
  }

  function updateDoc(id, patch) {
    setDocuments((prev) => prev.map((doc) => (doc.id === id ? { ...doc, ...patch } : doc)))
  }

  // documentRole: 'target'(왼쪽, 평가 대상 문서/기획서) | 'criteria'(오른쪽, 기준 문서·공고문)
  // — analyze_project()가 어떤 문서를 review 대상으로 쓰고 어떤 걸 RAG 근거로만 쓸지
  // 구분해야 해서 업로드 시점에 같이 넘긴다.
  async function uploadOne(file, documentRole) {
    const id = `${file.name}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
    setDocuments((prev) => [
      ...prev,
      { id, type: 'file', name: file.name, meta: formatFileSize(file.size), status: 'embedding', progress: 50 },
    ])

    try {
      const pid = await ensureProject()
      const doc = await uploadDocument(pid, file, 'pdf', documentRole)
      // 가은/Claude(2026-07-16): HWP/HWPX 변환 실패(용준, ai/rag/converters)는 HTTP
      // 200으로 응답이 오되 status="conversion_failed"로만 표시된다 — 예전엔 응답을
      // 검사 안 하고 무조건 'done'으로 표시해서 변환 실패가 조용히 묻혔다.
      // conversion_error(= DocumentConversionError.user_message)를 그대로 보여준다.
      if (doc.status === 'conversion_failed') {
        updateDoc(id, {
          status: 'error',
          progress: 100,
          meta: doc.conversion_metadata?.conversion_error || '문서를 변환하지 못했습니다.',
        })
        return
      }
      updateDoc(id, { status: 'done', progress: 100 })
    } catch (err) {
      updateDoc(id, { status: 'error', progress: 100, meta: err.message })
    }
  }

  function addFiles(fileList, documentRole) {
    const files = Array.from(fileList)
    const accepted = files.filter(isAcceptedDocument)
    const rejected = files.length - accepted.length

    setFileError(rejected > 0 ? `PDF, DOCX, PPTX, HWP, HWPX 파일만 업로드할 수 있습니다.` : '')
    if (accepted.length === 0) return

    accepted.forEach((file) => uploadOne(file, documentRole))
  }

  function handleFileInputChange(e, documentRole) {
    addFiles(e.target.files, documentRole)
    e.target.value = ''
  }

  async function handleFetchCriteriaUrl() {
    if (!criteriaUrl.trim()) {
      setCriteriaError('URL을 입력해주세요.')
      return
    }
    setCriteriaError('')
    setCriteriaLoading(true)
    try {
      const pid = await ensureProject()
      const result = await fetchUrl(criteriaUrl.trim(), pid)
      const id = `url-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
      const title = result.page_content?.title || criteriaUrl.trim()
      const attachmentCount = result.attachments?.length || 0
      const textLength = result.page_content?.text_length ?? 0
      // 가은/Claude(2026-07-18): 백엔드가 이미 만들어주는 warnings(JS 렌더링 의심 등)를
      // 예전엔 완전히 버리고 있었다 — sotong.go.kr URL로 실측: 게시판 상세 링크가
      // 실제 공고 내용이 아닌 페이지(첨부 0개, 본문 몇 글자)를 가리켜도 fetch 자체는
      // 200으로 성공해서 그냥 "✓ 완료"로만 보였다. warnings 또는 본문이 사실상 비어
      // 있으면 경고 배지 + 구체적인 이유를 보여준다.
      const looksEmpty = attachmentCount === 0 && textLength < _CRITERIA_MIN_TEXT_LENGTH
      const unsupportedLinks = result.unsupported_attachments || []
      // 가은/Claude(2026-07-18): url_loader.py의 _UNSUPPORTED_REASON과 같은 문자열 —
      // HWP 미지원 경고는 unsupported_attachments가 하나라도 있으면 항상 warnings에
      // 끼어 있어서, 이걸 그대로 "본문이 부실하다"는 신호로 썼더니 서울시 규제혁신
      // 공모전(본문에 심사기준·배점까지 다 있던 케이스)에서도 "확인 필요"가 잘못
      // 떴다(사용자 실측 지적, 2026-07-18) — HWP 경고는 따로 떼어서 다룬다.
      const HWP_UNSUPPORTED_WARNING = 'HWP/HWPX 형식은 현재 미지원이며 다운로드/파싱하지 않습니다.'
      const contentWarning = (result.warnings || []).find((w) => w !== HWP_UNSUPPORTED_WARNING)
      // 가은/Claude(2026-07-18): 본문 길이만으로는 "심사기준이 이미 본문에 있는지"를
      // 못 가른다 — 개인정보보호 공모전(1,112자, 요강 HWP만 언급)과 서울시 규제혁신
      // 공모전(4,278자, 배점표까지 명시) 둘 다 300자는 훌쩍 넘어서 길이 기준만으론
      // 둘을 구분 못 함. "배점/심사기준" 같은, 한국 공고문에서 심사기준 절에 거의
      // 항상 쓰이는 표현이 본문에 있는지로 판단한다.
      const CRITERIA_KEYWORDS = ['배점', '심사기준', '심사 기준', '평가기준', '평가 기준', '채점']
      const hasCriteriaSignal = CRITERIA_KEYWORDS.some((k) => (result.page_content?.text || '').includes(k))

      let status = 'done'
      let meta = attachmentCount > 0 ? `첨부파일 ${attachmentCount}개 수집` : new URL(result.origin_url).hostname

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
        // 본문에 이미 심사기준이 있어 보이면(hasCriteriaSignal) 경고 대신 선택적
        // 참고자료로만 안내한다.
        meta += ` · HWP 첨부 ${unsupportedLinks.length}개는 자동으로 못 읽었어요(선택 — 필요하면 아래에서 받아 올리세요)`
      }
      setDocuments((prev) => [...prev, { id, type: 'url', name: title, meta, status, unsupportedLinks }])
      setCriteriaUrl('')
    } catch (err) {
      setCriteriaError(err.message)
    } finally {
      setCriteriaLoading(false)
    }
  }

  function makeDropHandlers(setDragging, documentRole) {
    return {
      onDragOver: (e) => {
        e.preventDefault()
        setDragging(true)
      },
      onDragLeave: (e) => {
        e.preventDefault()
        setDragging(false)
      },
      onDrop: (e) => {
        e.preventDefault()
        setDragging(false)
        addFiles(e.dataTransfer.files, documentRole)
      },
    }
  }

  const targetDropHandlers = makeDropHandlers(setIsDragging, 'target')
  const criteriaDropHandlers = makeDropHandlers(setIsCriteriaDragging, 'criteria')

  // 가은/Claude(2026-07-16): STEP3 "공모전 분석"(멘토 추천/선택) 화면을 새로 만들면서,
  // "분석 시작"이 바로 실제 회의(/analyze, 1~2분 실제 OpenAI 호출)를 돌리는 대신 그 화면
  // (MentorSelectionPage)으로 이동하도록 바꿨다. 실제 /analyze 호출은 거기서 멘토
  // 2~4명을 고른 뒤 "멘토 선택하기"를 눌러야 시작된다.
  async function handleAnalyze() {
    setAnalyzeError('')
    setAnalyzing(true)
    try {
      const pid = await ensureProject()
      navigate(`/projects/${pid}/analysis`)
    } catch (err) {
      setAnalyzeError(err.message)
    } finally {
      setAnalyzing(false)
    }
  }

  return (
    <div style={styles.page}>
      <StepSidebar projectId={projectId} activeIndex={1} />

      <main style={styles.main}>
        <div style={styles.stepLabel}>STEP 2 / 5</div>
        <h1 style={styles.title}>공모전 정보 입력 · 문서 첨부</h1>

        {loadingExisting && <p style={styles.mutedNotice}>이전에 진행하던 프로젝트를 불러오는 중...</p>}

        <div style={styles.card}>
          <div style={styles.titleRow}>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              disabled={!!projectId}
              style={styles.titleInput}
              placeholder="프로젝트 제목"
            />
            <select
              value={docType}
              onChange={(e) => setDocType(e.target.value)}
              disabled={!!projectId}
              style={styles.docTypeSelect}
            >
              {DOC_TYPE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          <div style={styles.columns}>
            <div
              style={{ ...styles.dropzone, ...(isDragging ? styles.dropzoneDragging : {}) }}
              {...targetDropHandlers}
            >
              <UploadIcon />
              <div style={styles.dropzoneTitle}>{isDragging ? '여기에 놓으세요' : '평가 대상 문서'}</div>
              <div style={styles.dropzoneHint}>PDF, DOCX, PPTX, HWP, HWPX</div>
              <button style={styles.selectButton} onClick={() => targetFileInputRef.current?.click()}>
                파일 선택
              </button>
              <input
                ref={targetFileInputRef}
                type="file"
                accept={ACCEPTED_DOCUMENT_EXTENSIONS.join(',')}
                multiple
                style={styles.hiddenInput}
                onChange={(e) => handleFileInputChange(e, 'target')}
              />
            </div>

            <div style={styles.criteriaBox}>
              <div style={styles.criteriaHeader}>
                <span style={styles.criteriaTitle}>기준 문서 · 공고문</span>
                <span style={styles.proposalBadge}>제안 · 협의 필요</span>
              </div>

              <div style={styles.tabs}>
                <button
                  style={{ ...styles.tab, ...(criteriaTab === 'file' ? styles.tabActive : {}) }}
                  onClick={() => setCriteriaTab('file')}
                >
                  파일 업로드
                </button>
                <button
                  style={{ ...styles.tab, ...(criteriaTab === 'url' ? styles.tabActive : {}) }}
                  onClick={() => setCriteriaTab('url')}
                >
                  URL 입력
                </button>
              </div>

              {criteriaTab === 'url' ? (
                <>
                  <div style={styles.urlRow}>
                    <input
                      type="text"
                      value={criteriaUrl}
                      onChange={(e) => setCriteriaUrl(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleFetchCriteriaUrl()}
                      placeholder="https://example.com/공고문"
                      style={styles.urlInput}
                      disabled={criteriaLoading}
                    />
                    <button style={styles.fetchButton} onClick={handleFetchCriteriaUrl} disabled={criteriaLoading}>
                      {criteriaLoading ? '가져오는 중...' : '가져오기'}
                    </button>
                  </div>
                  {criteriaError && <p style={styles.fileError}>{criteriaError}</p>}
                  <p style={styles.helperText}>공모전·정부지원사업 공고 페이지 링크를 붙여넣으세요</p>
                </>
              ) : (
                <div
                  style={{
                    ...styles.dropzone,
                    ...styles.criteriaDropzone,
                    ...(isCriteriaDragging ? styles.dropzoneDragging : {}),
                  }}
                  {...criteriaDropHandlers}
                >
                  <div style={styles.criteriaDropzoneLeft}>
                    <UploadIcon />
                    <div>
                      <div style={styles.criteriaDropzoneTitle}>
                        {isCriteriaDragging ? '여기에 놓으세요' : '평가 기준 문서'}
                      </div>
                      <div style={styles.dropzoneHint}>PDF, DOCX, PPTX, HWP, HWPX</div>
                    </div>
                  </div>
                  <button
                    style={{ ...styles.selectButton, marginTop: 0, flexShrink: 0 }}
                    onClick={() => criteriaFileInputRef.current?.click()}
                  >
                    파일 선택
                  </button>
                  <input
                    ref={criteriaFileInputRef}
                    type="file"
                    accept={ACCEPTED_DOCUMENT_EXTENSIONS.join(',')}
                    multiple
                    style={styles.hiddenInput}
                    onChange={(e) => handleFileInputChange(e, 'criteria')}
                  />
                </div>
              )}
            </div>
          </div>

          {fileError && <p style={styles.fileError}>{fileError}</p>}

          <div style={styles.uploadedHeader}>업로드된 문서</div>
          <div style={styles.uploadedList}>
            {documents.map((doc, i) => (
              <div key={doc.id}>
                <DocumentRow document={doc} />
                {i < documents.length - 1 && <div style={styles.rowDivider} />}
              </div>
            ))}
          </div>

          {analyzeError && <p style={styles.fileError}>{analyzeError}</p>}
          <div style={styles.analyzeRow}>
            <button style={styles.analyzeButton} onClick={handleAnalyze} disabled={analyzing}>
              {analyzing ? '분석 중...' : '분석 시작'}
            </button>
          </div>
        </div>
      </main>
    </div>
  )
}

const ACCENT = '#7c4dff'

const styles = {
  page: {
    minHeight: '100vh',
    display: 'grid',
    gridTemplateColumns: '260px 1fr',
    background: '#f7f7fb',
    color: '#1f2333',
  },
  main: { padding: '24px 32px', maxWidth: 760, overflowY: 'auto' },
  stepLabel: { fontSize: 12, fontWeight: 700, color: ACCENT, letterSpacing: 0.5 },
  title: { fontSize: 22, fontWeight: 700, margin: '4px 0 20px' },
  mutedNotice: { margin: '0 0 16px', fontSize: 13, color: '#8b8fa3' },
  card: {
    background: '#fff',
    border: '1px solid #ece9f7',
    borderRadius: 14,
    padding: 24,
  },
  titleRow: {
    display: 'flex',
    gap: 8,
  },
  titleInput: {
    flex: 1,
    padding: '8px 10px',
    fontSize: 13,
    border: '1px solid #ded9f2',
    borderRadius: 8,
    outline: 'none',
    background: '#faf9ff',
    color: '#1f2333',
  },
  docTypeSelect: {
    padding: '8px 10px',
    fontSize: 13,
    border: '1px solid #ded9f2',
    borderRadius: 8,
    outline: 'none',
    background: '#faf9ff',
    color: '#1f2333',
  },
  columns: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: 16,
    marginTop: 24,
  },
  dropzone: {
    borderWidth: 1.5,
    borderStyle: 'dashed',
    borderColor: '#cfc7ef',
    borderRadius: 12,
    background: '#faf9ff',
    padding: '32px 16px',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 8,
    textAlign: 'center',
    transition: 'border-color 0.15s, background 0.15s',
  },
  dropzoneDragging: {
    borderColor: ACCENT,
    background: `${ACCENT}11`,
  },
  criteriaDropzone: {
    marginTop: 14,
    padding: '18px 16px',
    flexDirection: 'row',
    justifyContent: 'space-between',
    textAlign: 'left',
  },
  criteriaDropzoneLeft: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
  },
  criteriaDropzoneTitle: {
    fontSize: 15,
    fontWeight: 700,
    color: '#1f2333',
  },
  dropzoneTitle: {
    fontSize: 15,
    fontWeight: 700,
    color: '#1f2333',
    marginTop: 4,
  },
  dropzoneHint: {
    fontSize: 12,
    color: '#8b8fa3',
  },
  selectButton: {
    marginTop: 8,
    padding: '8px 18px',
    borderRadius: 999,
    border: 'none',
    background: ACCENT,
    color: '#fff',
    fontSize: 13,
    fontWeight: 600,
    cursor: 'pointer',
  },
  hiddenInput: {
    display: 'none',
  },
  criteriaBox: {
    border: '1px solid #ece9f7',
    borderRadius: 12,
    padding: 16,
  },
  criteriaHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  criteriaTitle: {
    fontSize: 14,
    fontWeight: 700,
    color: '#1f2333',
  },
  proposalBadge: {
    fontSize: 11,
    fontWeight: 600,
    color: '#9a6400',
    background: '#fdf1d6',
    padding: '3px 8px',
    borderRadius: 999,
  },
  tabs: {
    display: 'flex',
    gap: 4,
    background: '#f0eefc',
    borderRadius: 999,
    padding: 4,
    marginTop: 14,
  },
  tab: {
    flex: 1,
    padding: '7px 0',
    borderRadius: 999,
    border: 'none',
    background: 'transparent',
    color: '#8b8fa3',
    fontSize: 13,
    fontWeight: 600,
    cursor: 'pointer',
  },
  tabActive: {
    background: '#fff',
    color: ACCENT,
    boxShadow: '0 1px 4px rgba(124, 77, 255, 0.15)',
  },
  urlRow: {
    display: 'flex',
    gap: 8,
    marginTop: 14,
  },
  urlInput: {
    flex: 1,
    padding: '10px 12px',
    fontSize: 13,
    border: '1px solid #ded9f2',
    borderRadius: 8,
    outline: 'none',
    background: '#faf9ff',
    color: '#1f2333',
    minWidth: 0,
  },
  fetchButton: {
    padding: '0 16px',
    borderRadius: 8,
    border: 'none',
    background: ACCENT,
    color: '#fff',
    fontSize: 13,
    fontWeight: 600,
    cursor: 'pointer',
  },
  helperText: {
    margin: '10px 0 0',
    fontSize: 12,
    color: '#a1a5b8',
  },
  fileError: {
    margin: '16px 0 0',
    fontSize: 13,
    color: '#d64545',
  },
  uploadedHeader: {
    fontSize: 13,
    fontWeight: 700,
    color: '#1f2333',
    marginTop: 28,
    marginBottom: 8,
  },
  uploadedList: {
    border: '1px solid #ece9f7',
    borderRadius: 12,
    padding: '4px 12px',
  },
  rowDivider: {
    borderTop: '1px solid #f2f1f8',
  },
  analyzeRow: {
    display: 'flex',
    justifyContent: 'center',
    marginTop: 28,
  },
  analyzeButton: {
    padding: '12px 40px',
    borderRadius: 999,
    border: 'none',
    background: ACCENT,
    color: '#fff',
    fontSize: 15,
    fontWeight: 700,
    cursor: 'pointer',
  },
}
