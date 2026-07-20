import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getProjects, deleteProject } from '../api/projectApi'
import StatusBadge from '../components/common/StatusBadge'
import StepSidebar from '../components/wizard/StepSidebar'

function FolderIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#7c4dff" strokeWidth="1.8">
      <path d="M3 6.5C3 5.67 3.67 5 4.5 5h4.4c.35 0 .68.14.93.38L11 6.5h8.5c.83 0 1.5.67 1.5 1.5v9.5c0 .83-.67 1.5-1.5 1.5h-15C3.67 19 3 18.33 3 17.5v-11Z" />
    </svg>
  )
}

function ChevronIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#a1a5b8" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 6l6 6-6 6" />
    </svg>
  )
}

// 가은/Claude(2026-07-20): "리스트에서 새 프로젝트를 왼->오로 밀면 삭제 버튼이 나오게"
// — 라이브러리 없이 pointer 이벤트로 직접 구현. 왼쪽 밑에 항상 깔려 있는 삭제 버튼을
// 앞의 행(row)을 오른쪽으로 끌어서(translateX) 드러내는 방식. 드래그였는지 탭이었는지는
// 이동 거리(CLICK_MOVE_THRESHOLD)로 구분해서, 살짝 흔들린 탭까지 드래그로 오인해 원래
// 있던 "행 클릭 -> 상세 이동" 동작을 깨지 않게 한다. 한 번에 하나의 행만 열려있게
// 부모(ProjectListPage)가 openRowId로 관리한다 — 다른 행을 열면 이전 행은 자동으로 닫힘.
// 가은/Claude(2026-07-20): "버튼 나온 데서 조금만 더 밀면 삭제 팝업 뜨게" — 버튼이 열리는
// REVEAL_WIDTH를 넘어 FULL_SWIPE_WIDTH까지 더 끌고 놓으면(iOS 메일 앱의 완전 스와이프
// 삭제와 동일한 패턴) 버튼을 따로 안 눌러도 바로 onDelete(확인 팝업)를 띄운다. 완전
// 스와이프 구간에 들어서면 버튼 배경/문구를 바꿔서 "놓으면 삭제"라는 걸 미리 알려준다.
const REVEAL_WIDTH = 88
const FULL_SWIPE_WIDTH = REVEAL_WIDTH + 70
const MAX_DRAG = FULL_SWIPE_WIDTH + 20
const CLICK_MOVE_THRESHOLD = 6

function SwipeableRow({ project, isOpen, isLast, deleting, onOpenChange, onDelete, onNavigate }) {
  const [dragX, setDragX] = useState(isOpen ? REVEAL_WIDTH : 0)
  const [dragging, setDragging] = useState(false)
  const gestureRef = useRef({ startX: 0, baseX: 0, moved: false })

  useEffect(() => {
    if (!dragging) setDragX(isOpen ? REVEAL_WIDTH : 0)
  }, [isOpen, dragging])

  function handlePointerDown(e) {
    gestureRef.current = { startX: e.clientX, baseX: isOpen ? REVEAL_WIDTH : 0, moved: false }
    setDragging(true)
    // 빠르게 끌면 포인터가 행 영역을 벗어날 수 있어서, capture로 이후 move/up 이벤트를
    // 계속 이 요소로 받는다(터치에서 특히 중요).
    e.currentTarget.setPointerCapture?.(e.pointerId)
  }

  function handlePointerMove(e) {
    if (!dragging) return
    const delta = e.clientX - gestureRef.current.startX
    if (Math.abs(delta) > CLICK_MOVE_THRESHOLD) gestureRef.current.moved = true
    setDragX(Math.max(0, Math.min(MAX_DRAG, gestureRef.current.baseX + delta)))
  }

  function endDrag() {
    if (!dragging) return
    setDragging(false)
    if (dragX >= FULL_SWIPE_WIDTH) {
      // 완전 스와이프 — 버튼을 따로 누르지 않아도 바로 삭제 확인을 띄운다. 확인 팝업에서
      // 취소하면 onDelete가 삭제를 진행하지 않으니, 버튼이 열려 있는 상태로만 되돌린다.
      setDragX(REVEAL_WIDTH)
      onOpenChange(project.id)
      onDelete(project.id)
      return
    }
    const shouldOpen = dragX > REVEAL_WIDTH / 2
    setDragX(shouldOpen ? REVEAL_WIDTH : 0)
    onOpenChange(shouldOpen ? project.id : null)
  }

  function handleRowClick() {
    if (gestureRef.current.moved) return // 드래그 끝의 클릭 이벤트는 무시
    if (isOpen) {
      onOpenChange(null) // 열려있는 상태에서 행을 탭하면 닫기만 한다
      return
    }
    onNavigate(project.id)
  }

  const pastFull = dragX >= FULL_SWIPE_WIDTH
  // 버튼 너비를 dragX만큼 늘려서, REVEAL_WIDTH를 넘어 더 끄는 동안 행과 버튼 사이에
  // 빈 틈(카드 배경)이 보이지 않고 버튼이 같이 늘어나는 것처럼 보이게 한다.
  const buttonWidth = Math.max(REVEAL_WIDTH, dragX)

  return (
    <div style={{ position: 'relative', overflow: 'hidden', borderBottom: isLast ? 'none' : '1px solid #f2f1f8' }}>
      <button
        style={{
          ...styles.deleteButton,
          width: buttonWidth,
          background: pastFull ? '#b52f2f' : '#d64545',
          transition: dragging ? 'none' : 'width 0.2s ease, background 0.15s ease',
        }}
        disabled={deleting}
        onClick={(e) => {
          e.stopPropagation()
          onDelete(project.id)
        }}
      >
        {deleting ? '삭제 중...' : pastFull ? '놓으면 삭제' : '삭제'}
      </button>
      <div
        style={{
          ...styles.row,
          transform: `translateX(${dragX}px)`,
          transition: dragging ? 'none' : 'transform 0.2s ease',
        }}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={endDrag}
        onPointerLeave={endDrag}
        onPointerCancel={endDrag}
        onClick={handleRowClick}
      >
        <div style={styles.rowLeft}>
          <FolderIcon />
          <div>
            <div style={styles.rowTitle}>{project.title}</div>
            <div style={styles.rowDate}>{String(project.created_at).slice(0, 10)} 생성</div>
          </div>
        </div>
        <div style={styles.rowRight}>
          <StatusBadge status={project.status} />
          <ChevronIcon />
        </div>
      </div>
    </div>
  )
}

export default function ProjectListPage() {
  const navigate = useNavigate()
  const [projects, setProjects] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [openRowId, setOpenRowId] = useState(null)
  const [deletingId, setDeletingId] = useState(null)
  const [deleteError, setDeleteError] = useState('')

  useEffect(() => {
    getProjects()
      .then((data) => {
        setProjects(data)
        setLoading(false)
      })
      .catch((err) => {
        setError(err.message)
        setLoading(false)
      })
  }, [])

  function handleDelete(projectId) {
    if (deletingId) return
    const project = projects.find((p) => p.id === projectId)
    if (!window.confirm(`"${project?.title ?? '이 프로젝트'}"를 삭제할까요? 되돌릴 수 없습니다.`)) {
      return
    }
    setDeleteError('')
    setDeletingId(projectId)
    deleteProject(projectId)
      .then(() => {
        setProjects((prev) => prev.filter((p) => p.id !== projectId))
        setOpenRowId(null)
      })
      .catch((err) => setDeleteError(err.message))
      .finally(() => setDeletingId(null))
  }

  return (
    <div style={styles.page}>
      <StepSidebar activeIndex={0} />

      <main style={styles.main}>
        <div style={styles.stepLabel}>STEP 1 / 5</div>
        <div style={styles.header}>
          <h1 style={styles.title}>내 프로젝트</h1>
          <button style={styles.newButton} onClick={() => navigate('/projects/new')}>
            + 새 프로젝트
          </button>
        </div>

        {deleteError && <p style={styles.deleteErrorText}>{deleteError}</p>}

        <div style={styles.card}>
          {loading && <p style={styles.empty}>불러오는 중...</p>}
          {!loading && error && <p style={styles.empty}>{error}</p>}
          {!loading && !error && projects.length === 0 && <p style={styles.empty}>아직 프로젝트가 없습니다.</p>}

          {!error &&
            projects.map((project, i) => (
              <SwipeableRow
                key={project.id}
                project={project}
                isLast={i === projects.length - 1}
                isOpen={openRowId === project.id}
                deleting={deletingId === project.id}
                onOpenChange={setOpenRowId}
                onDelete={handleDelete}
                // 가은/Claude(2026-07-21): 실측 요청 — "내 프로젝트"에서 프로젝트를
                // 열면 board에서 올린 공고문·기획서·분석결과가 보여야 한다. 구
                // ProjectDetailPage(/projects/:id)는 board와 무관한 레거시 화면이라
                // 대신 /board로 이어서 하기(ReviewBoardPrototype.jsx의 ?projectId=
                // 처리부 참고) 보낸다.
                onNavigate={(id) => navigate(`/board?projectId=${id}`)}
              />
            ))}
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
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    margin: '4px 0 20px',
  },
  title: {
    margin: 0,
    fontSize: 22,
    fontWeight: 700,
  },
  newButton: {
    padding: '8px 16px',
    borderRadius: 999,
    background: ACCENT,
    border: 'none',
    color: '#fff',
    fontSize: 13,
    fontWeight: 600,
    cursor: 'pointer',
  },
  deleteErrorText: { color: '#d64545', fontSize: 13, marginBottom: 10 },
  card: {
    background: '#fff',
    border: '1px solid #ece9f7',
    borderRadius: 14,
    padding: '4px 20px',
  },
  empty: {
    color: '#8b8fa3',
    fontSize: 14,
    padding: '24px 0',
    textAlign: 'center',
  },
  row: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '16px 4px',
    cursor: 'pointer',
    background: '#fff',
    touchAction: 'pan-y',
    userSelect: 'none',
  },
  rowLeft: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
  },
  rowTitle: {
    fontSize: 15,
    fontWeight: 600,
    color: '#1f2333',
  },
  rowDate: {
    fontSize: 13,
    color: '#8b8fa3',
    marginTop: 4,
  },
  rowRight: {
    display: 'flex',
    alignItems: 'center',
    gap: 14,
  },
  deleteButton: {
    position: 'absolute',
    top: 0,
    left: 0,
    bottom: 0,
    width: REVEAL_WIDTH,
    border: 'none',
    background: '#d64545',
    color: '#fff',
    fontSize: 13,
    fontWeight: 700,
    cursor: 'pointer',
  },
}
