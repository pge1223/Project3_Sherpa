import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import DocumentRow from '../components/upload/DocumentRow'
import { isAcceptedDocument, formatFileSize, ACCEPTED_DOCUMENT_EXTENSIONS } from '../utils/file'
import SpaceBackground from '../components/landing/SpaceBackground'
import { createProject, analyzeProject } from '../api/projectApi'
import { uploadDocument, fetchUrl } from '../api/documentApi'

const DOC_TYPE_OPTIONS = [
  { value: 'competition', label: '공모전' },
  { value: 'government_support', label: '정부지원사업' },
  { value: 'startup', label: '사업계획서(스타트업)' },
]

function UploadIcon() {
  return (
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#5c86ac" strokeWidth="1.8">
      <path d="M12 16V4M12 4 7 9M12 4l5 5" />
      <path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
    </svg>
  )
}

export default function DocumentUploadPage() {
  const navigate = useNavigate()
  const [criteriaTab, setCriteriaTab] = useState('url')
  const [criteriaUrl, setCriteriaUrl] = useState('')
  const [documents, setDocuments] = useState([])
  const [isDragging, setIsDragging] = useState(false)
  const [isCriteriaDragging, setIsCriteriaDragging] = useState(false)
  const [fileError, setFileError] = useState('')
  const [title, setTitle] = useState('새 프로젝트')
  const [docType, setDocType] = useState(DOC_TYPE_OPTIONS[0].value)
  const [projectId, setProjectId] = useState(null)
  const [criteriaLoading, setCriteriaLoading] = useState(false)
  const [criteriaError, setCriteriaError] = useState('')
  const [analyzing, setAnalyzing] = useState(false)
  const [analyzeError, setAnalyzeError] = useState('')

  const targetFileInputRef = useRef(null)
  const criteriaFileInputRef = useRef(null)

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
      await uploadDocument(pid, file, 'pdf', documentRole)
      updateDoc(id, { status: 'done', progress: 100 })
    } catch (err) {
      updateDoc(id, { status: 'error', progress: 100, meta: err.message })
    }
  }

  function addFiles(fileList, documentRole) {
    const files = Array.from(fileList)
    const accepted = files.filter(isAcceptedDocument)
    const rejected = files.length - accepted.length

    setFileError(rejected > 0 ? `PDF, DOCX, PPTX 파일만 업로드할 수 있습니다.` : '')
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
      const meta = attachmentCount > 0 ? `첨부파일 ${attachmentCount}개 수집` : new URL(result.origin_url).hostname
      setDocuments((prev) => [...prev, { id, type: 'url', name: title, meta, status: 'done' }])
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

  async function handleAnalyze() {
    setAnalyzeError('')
    setAnalyzing(true)
    try {
      const pid = await ensureProject()
      const result = await analyzeProject(pid)
      sessionStorage.setItem(`analysis:${pid}`, JSON.stringify(result))
      navigate(`/projects/${pid}`)
    } catch (err) {
      setAnalyzeError(err.message)
    } finally {
      setAnalyzing(false)
    }
  }

  return (
    <div style={styles.page}>
      <SpaceBackground />
      <div style={styles.pageInner}>
        <img src="/images/logo4.png" alt="AI Review Board" style={styles.logo} />

        <button style={styles.backButton} onClick={() => navigate('/projects')}>
          ← 뒤로
        </button>

        <div style={styles.card}>
        <div style={styles.header}>
          <div style={{ flex: 1 }}>
            <h1 style={styles.title}>문서 업로드</h1>
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
          </div>
          <button style={styles.menuButton}>⋯</button>
        </div>

        <div style={styles.columns}>
          <div
            style={{ ...styles.dropzone, ...(isDragging ? styles.dropzoneDragging : {}) }}
            {...targetDropHandlers}
          >
            <UploadIcon />
            <div style={styles.dropzoneTitle}>{isDragging ? '여기에 놓으세요' : '평가 대상 문서'}</div>
            <div style={styles.dropzoneHint}>PDF, DOCX, PPTX</div>
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
                    <div style={styles.dropzoneHint}>PDF, DOCX, PPTX</div>
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
      </div>
    </div>
  )
}

const styles = {
  page: {
    position: 'relative',
    zIndex: 1,
    minHeight: '100vh',
    padding: '48px 24px',
    display: 'flex',
    justifyContent: 'center',
  },
  pageInner: {
    position: 'relative',
    zIndex: 2,
    width: '100%',
    maxWidth: 760,
  },
  logo: {
    display: 'block',
    width: 240,
    height: 'auto',
    margin: '0 auto 20px',
  },
  backButton: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    padding: '8px 4px',
    marginBottom: 12,
    border: 'none',
    background: 'transparent',
    color: '#cdd9f7',
    fontSize: 14,
    fontWeight: 600,
    cursor: 'pointer',
  },
  card: {
    width: '100%',
    background: '#fff',
    border: '1px solid #d9e8f5',
    borderRadius: 16,
    boxShadow: '0 8px 24px rgba(43, 111, 178, 0.10)',
    padding: 28,
    height: 'fit-content',
  },
  header: {
    display: 'flex',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
  },
  title: {
    margin: 0,
    fontSize: 20,
    fontWeight: 700,
    color: '#1a3a5c',
  },
  subtitle: {
    margin: '4px 0 0',
    fontSize: 13,
    color: '#7994ac',
  },
  titleRow: {
    display: 'flex',
    gap: 8,
    marginTop: 8,
  },
  titleInput: {
    flex: 1,
    padding: '8px 10px',
    fontSize: 13,
    border: '1px solid #cfe0f0',
    borderRadius: 8,
    outline: 'none',
    background: '#f8fbfe',
    color: '#17324a',
  },
  docTypeSelect: {
    padding: '8px 10px',
    fontSize: 13,
    border: '1px solid #cfe0f0',
    borderRadius: 8,
    outline: 'none',
    background: '#f8fbfe',
    color: '#17324a',
  },
  menuButton: {
    width: 32,
    height: 32,
    borderRadius: '50%',
    border: '1px solid #d9e8f5',
    background: '#f5faff',
    color: '#5c86ac',
    fontSize: 16,
    lineHeight: 1,
    cursor: 'pointer',
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
    borderColor: '#b8d3ea',
    borderRadius: 12,
    background: '#f5faff',
    padding: '32px 16px',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 8,
    textAlign: 'center',
    transition: 'border-color 0.15s, background 0.15s',
  },
  dropzoneDragging: {
    borderColor: '#2f7fd1',
    background: '#e7f2fc',
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
    color: '#17324a',
  },
  dropzoneTitle: {
    fontSize: 15,
    fontWeight: 700,
    color: '#17324a',
    marginTop: 4,
  },
  dropzoneHint: {
    fontSize: 12,
    color: '#7994ac',
  },
  selectButton: {
    marginTop: 8,
    padding: '8px 18px',
    borderRadius: 999,
    border: 'none',
    background: '#2f7fd1',
    color: '#fff',
    fontSize: 13,
    fontWeight: 600,
    cursor: 'pointer',
  },
  hiddenInput: {
    display: 'none',
  },
  criteriaBox: {
    border: '1px solid #d9e8f5',
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
    color: '#17324a',
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
    background: '#eef5fb',
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
    color: '#7994ac',
    fontSize: 13,
    fontWeight: 600,
    cursor: 'pointer',
  },
  tabActive: {
    background: '#fff',
    color: '#17324a',
    boxShadow: '0 1px 4px rgba(43, 111, 178, 0.15)',
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
    border: '1px solid #cfe0f0',
    borderRadius: 8,
    outline: 'none',
    background: '#f8fbfe',
    color: '#17324a',
    minWidth: 0,
  },
  fetchButton: {
    padding: '0 16px',
    borderRadius: 8,
    border: 'none',
    background: '#2f7fd1',
    color: '#fff',
    fontSize: 13,
    fontWeight: 600,
    cursor: 'pointer',
  },
  helperText: {
    margin: '10px 0 0',
    fontSize: 12,
    color: '#94a9bd',
  },
  fileError: {
    margin: '16px 0 0',
    fontSize: 13,
    color: '#d64545',
  },
  uploadedHeader: {
    fontSize: 13,
    fontWeight: 700,
    color: '#17324a',
    marginTop: 28,
    marginBottom: 8,
  },
  uploadedList: {
    border: '1px solid #e2edf7',
    borderRadius: 12,
    padding: '4px 12px',
  },
  rowDivider: {
    borderTop: '1px solid #eef5fb',
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
    background: '#e0413a',
    color: '#fff',
    fontSize: 15,
    fontWeight: 700,
    cursor: 'pointer',
  },
}
