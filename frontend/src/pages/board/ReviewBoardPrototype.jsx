import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Link2, Upload, FileText, Sparkles,
  CheckCircle2, Circle, AlertCircle, Send, Award, Target, ShieldCheck,
  ArrowRight, TrendingUp, ChevronDown, ChevronUp,
} from "lucide-react";
import { createProject } from "../../api/projectApi";
import {
  fetchUrl as fetchCriteriaUrl,
  uploadDocument,
  getDocumentStatus,
  getAnnouncementAnalysis,
} from "../../api/documentApi";
import { analyzeProject, getAnalyzeProgress, getMentorCandidates } from "../../api/projectApi";
import { isAcceptedDocument, formatFileSize, ACCEPTED_DOCUMENT_EXTENSIONS } from "../../utils/file";
import { assessCriteriaContent } from "../../utils/criteriaAssessment";

// 가은/Claude(2026-07-20, INF-007): fetch-url이 색인을 백그라운드로 넘기면서
// document_status가 "indexing"으로 오면 폴링해야 한다 — DocumentUploadPage.jsx와 동일 값.
const _DOCUMENT_STATUS_POLL_INTERVAL_MS = 2000
const _DOCUMENT_STATUS_POLL_MAX_ATTEMPTS = 90 // 2s * 90 = 3분

/* 가은/Claude(2026-07-20): "작성 전(주제 발굴)/작성 후(문서 피드백)" 2-모드
 * 신규 플로우. docs/REVIEW_BOARD_서비스_방향성_정리_20260720.md의 방향을
 * 구현한 화면으로, "작성 전(주제 발굴)" 경로(ideation/ideation_result)는 아직
 * 더미 데이터다 — 백엔드에 주제 발굴 회의 API가 없어서다.
 * "작성 후(문서 피드백)" 경로는 기존 /projects/new(평가 대상 문서 업로드)와
 * MentorSelectionPage(분석 시작 → analyzeProject)의 실제 로직을 그대로
 * 재사용한다 — 다만 멘토 선택 화면 없이 추천 멘토를 자동으로 전부 쓴다.
 * 배경·색 팔레트는 웜 화이트(#faf8f4) 고정 디자인이다(가은 확정) — OS
 * 다크모드를 따라 자동 전환하지 않는다.
 */

const STAGE_LABELS = {
  entry: "공모전 입력",
  analysis: "공모전 분석",
  ideation: "주제 아이디어 회의",
  ideation_result: "주제 확정",
  upload: "기획서 업로드 · 분석",
};

const FLOW_BY_MODE = {
  pre: ["entry", "analysis", "ideation", "ideation_result"],
  post: ["entry", "analysis", "upload"],
};

const MIN_MENTORS = 2
const MAX_MENTORS = 4
const ANALYZE_POLL_INTERVAL_MS = 1000

function Shell({ children, active, mode, onNavigate, showNav }) {
  const flow = mode ? FLOW_BY_MODE[mode] : ["entry"];

  return (
    <div className="rb-root">
      <style>{`
        .rb-root{
          --bg-0:#faf8f4; --bg-1:#ffffff; --bg-2:#f1eee5;
          --glass: rgba(255,255,255,0.72); --glass-border: rgba(28,26,46,0.10);
          --purple:#7c5cea; --purple-dim: rgba(124,92,234,0.12);
          --coral:#e0603d; --coral-dim: rgba(224,96,61,0.12);
          --green:#16a37a; --green-dim: rgba(22,163,122,0.12);
          --amber:#b8830b; --amber-dim: rgba(184,131,11,0.14);
          --text-0:#1c1a2e; --text-1:#5b5770; --text-2:#918d9f;
          --cream:#f4efe2; --cream-line:#e7ddc4;
          --mono: 'JetBrains Mono', ui-monospace, monospace;
        }
        .rb-root{
          min-height:100vh; width:100%;
          background:
            radial-gradient(1100px 600px at 12% -10%, rgba(124,92,234,0.10), transparent 60%),
            radial-gradient(900px 500px at 100% 10%, rgba(22,163,122,0.07), transparent 55%),
            radial-gradient(800px 500px at 50% 110%, rgba(224,96,61,0.06), transparent 55%),
            var(--bg-0);
          color:var(--text-0);
          font-family:'Pretendard', -apple-system, sans-serif;
          display:flex;
        }
        .rb-root .glass{ background:var(--glass); border:1px solid var(--glass-border); backdrop-filter: blur(14px); box-shadow: 0 2px 14px rgba(28,26,46,0.05); }
        .rb-root .mono{ font-family:var(--mono); letter-spacing:0.02em; }
        .rb-root .navrail{ width:220px; flex-shrink:0; border-right:1px solid var(--glass-border); padding:24px 14px; }
        .rb-root .navitem{ display:flex; align-items:center; gap:10px; padding:10px 12px; border-radius:10px; font-size:13px; color:var(--text-2); cursor:pointer; margin-bottom:4px; }
        .rb-root .navitem:hover{ background:var(--bg-2); }
        .rb-root .navitem.active{ background:var(--purple-dim); color:var(--text-0); }
        .rb-root .navitem.done{ color:var(--text-1); }
        .rb-root .main{ flex:1; min-width:0; padding:32px 40px; overflow-y:auto; }
        .rb-root .badge{ display:inline-flex; align-items:center; gap:6px; font-size:11px; padding:3px 9px; border-radius:99px; font-family:var(--mono); }
        .rb-root .badge.purple{ background:var(--purple-dim); color:var(--purple); }
        .rb-root .badge.coral{ background:var(--coral-dim); color:var(--coral); }
        .rb-root .badge.green{ background:var(--green-dim); color:var(--green); }
        .rb-root .badge.amber{ background:var(--amber-dim); color:var(--amber); }
        .rb-root .btn-primary{ background:linear-gradient(135deg, var(--purple), #8b6ef0); color:#0b0a16; font-weight:600; border:none; border-radius:12px; padding:11px 20px; cursor:pointer; font-size:14px; }
        .rb-root .btn-primary:disabled{ opacity:0.4; cursor:not-allowed; }
        .rb-root .btn-ghost{ background:transparent; border:1px solid var(--glass-border); color:var(--text-1); border-radius:12px; padding:10px 18px; cursor:pointer; font-size:14px; }
        .rb-root .btn-ghost:hover{ background:var(--bg-2); }
        .rb-root .card{ border-radius:16px; padding:20px; }
        .rb-root .progress-track{ height:8px; border-radius:999px; background:var(--bg-2); overflow:hidden; }
        .rb-root .progress-fill{ height:100%; border-radius:999px; background:linear-gradient(135deg, var(--purple), #8b6ef0); transition:width .5s ease; }
        @media (max-width: 780px){
          .rb-root{ flex-direction:column; }
          .rb-root .navrail{ display:none; }
          .rb-root .main{ padding:20px; }
          .rb-grid-2{ grid-template-columns: 1fr !important; }
        }
      `}</style>

      {showNav && (
        <div className="navrail glass">
          <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 20, letterSpacing: "0.02em" }}>
            AI Review Board
          </div>
          {flow.map((k) => (
            <div
              key={k}
              className={`navitem ${active === k ? "active" : ""} ${flow.indexOf(k) < flow.indexOf(active) ? "done" : ""}`}
              onClick={() => onNavigate(k)}
            >
              {flow.indexOf(k) < flow.indexOf(active) ? <CheckCircle2 size={14} color="var(--green)" /> : <Circle size={13} />}
              {STAGE_LABELS[k]}
            </div>
          ))}
        </div>
      )}
      <div className="main">{children}</div>
    </div>
  );
}

/* ---------------- 1. 진입화면 : 모드 선택 + 공고 입력 ---------------- */
/* 가은/Claude(2026-07-20): 실측 버그 — "공모전 공고 URL 입력하면 안 먹어" 제보.
 * 원인은 이 화면 URL 입력창이 그냥 텍스트 필드였고, "분석 시작"을 눌러야만(그것도
 * 조용히 실패를 삼키며) 한 번 fetchUrl을 시도했기 때문 — 실패해도 아무 표시가
 * 없었다. DocumentUploadPage.jsx(/projects/new)의 "기준 문서·공고문" 로직(URL 탭 +
 * 파일 업로드 탭, 전용 "가져오기" 버튼, 진행 상태·에러 표시, 색인 폴링)을 그대로
 * 옮겨왔다.
 */
function EntryScreen({ onEnter, loading, error, projectId, ensureProject, documents, setDocuments }) {
  const [mode, setMode] = useState(null);
  const [criteriaTab, setCriteriaTab] = useState('url');
  const [criteriaUrl, setCriteriaUrl] = useState('');
  const [criteriaLoading, setCriteriaLoading] = useState(false);
  const [criteriaError, setCriteriaError] = useState('');
  const [isCriteriaDragging, setIsCriteriaDragging] = useState(false);
  const criteriaFileInputRef = useRef(null);

  function updateDoc(id, patch) {
    setDocuments((prev) => prev.map((doc) => (doc.id === id ? { ...doc, ...patch } : doc)));
  }

  function pollDocumentIndexing(pid, documentId, rowId, contentStatus, contentMeta) {
    let attempts = 0;
    const timer = setInterval(async () => {
      attempts += 1;
      try {
        const statusResult = await getDocumentStatus(pid, documentId);
        if (statusResult.status === 'indexing') {
          if (attempts >= _DOCUMENT_STATUS_POLL_MAX_ATTEMPTS) {
            clearInterval(timer);
            updateDoc(rowId, { status: 'error', meta: '색인 상태 확인이 너무 오래 걸리고 있어요 — 새로고침해서 다시 확인해주세요.' });
          }
          return;
        }
        clearInterval(timer);
        if (statusResult.status === 'indexing_failed') {
          updateDoc(rowId, { status: 'error', meta: '공고문 색인 중 오류가 발생했습니다.' });
        } else if (statusResult.status === 'indexing_timeout') {
          updateDoc(rowId, { status: 'error', meta: '색인이 시간 내에 끝나지 않았습니다 — 다시 시도해주세요.' });
        } else {
          updateDoc(rowId, { status: contentStatus, meta: contentMeta });
        }
      } catch (err) {
        clearInterval(timer);
        updateDoc(rowId, { status: 'error', meta: err.message });
      }
    }, _DOCUMENT_STATUS_POLL_INTERVAL_MS);
  }

  async function handleFetchCriteriaUrl() {
    if (!criteriaUrl.trim()) {
      setCriteriaError('URL을 입력해주세요.');
      return;
    }
    setCriteriaError('');
    setCriteriaLoading(true);
    try {
      const pid = await ensureProject();
      const result = await fetchCriteriaUrl(criteriaUrl.trim(), pid);
      const id = `url-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      const title = result.page_content?.title || criteriaUrl.trim();
      const { status: contentStatus, meta: contentMeta } = assessCriteriaContent(result);

      // 가은/Claude(2026-07-21): 실측 지적 — 여기서 원문 앞부분 300자를 그대로 미리보기로
      // 보여줬더니 메뉴/내비게이션 텍스트("공지사항 - 공지사항 - 뉴포커스 - ...")가 그대로
      // 나왔다. 원문 요약은 "공모전 분석" 화면(AnalysisScreen)이 LLM으로 뽑은 요약을 대신
      // 보여주므로, 여기서는 원문 슬라이스를 더 이상 안 만든다.
      if (result.document_status === 'indexing' && result.document_id) {
        setDocuments((prev) => [...prev, { id, name: title, meta: '공고문을 색인하는 중...', status: 'embedding' }]);
        pollDocumentIndexing(pid, result.document_id, id, contentStatus, contentMeta);
      } else {
        setDocuments((prev) => [...prev, { id, name: title, meta: contentMeta, status: contentStatus }]);
      }
      setCriteriaUrl('');
    } catch (err) {
      setCriteriaError(err.message);
    } finally {
      setCriteriaLoading(false);
    }
  }

  async function uploadCriteriaFile(file) {
    const id = `${file.name}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    setDocuments((prev) => [...prev, { id, name: file.name, meta: formatFileSize(file.size), status: 'embedding' }]);
    try {
      const pid = await ensureProject();
      const doc = await uploadDocument(pid, file, 'pdf', 'criteria');
      if (doc.status === 'conversion_failed') {
        updateDoc(id, { status: 'error', meta: doc.conversion_metadata?.conversion_error || '문서를 변환하지 못했습니다.' });
        return;
      }
      updateDoc(id, { status: 'done', meta: formatFileSize(file.size) });
    } catch (err) {
      updateDoc(id, { status: 'error', meta: err.message });
    }
  }

  function addCriteriaFiles(fileList) {
    const files = Array.from(fileList);
    const accepted = files.filter(isAcceptedDocument);
    const rejected = files.length - accepted.length;
    setCriteriaError(rejected > 0 ? 'PDF, DOCX, PPTX, HWP, HWPX 파일만 업로드할 수 있습니다.' : '');
    accepted.forEach(uploadCriteriaFile);
  }

  const criteriaDropHandlers = {
    onDragOver: (e) => { e.preventDefault(); setIsCriteriaDragging(true); },
    onDragLeave: (e) => { e.preventDefault(); setIsCriteriaDragging(false); },
    onDrop: (e) => { e.preventDefault(); setIsCriteriaDragging(false); addCriteriaFiles(e.dataTransfer.files); },
  };

  return (
    <div style={{ maxWidth: 760, margin: "40px auto" }}>
      <div className="badge purple mono" style={{ marginBottom: 14 }}>IT 공모전 · MVP</div>
      <h1 style={{ fontSize: 30, fontWeight: 700, lineHeight: 1.35, marginBottom: 10 }}>
        지금 어떤 상태이세요?
      </h1>
      <p style={{ color: "var(--text-2)", fontSize: 14, marginBottom: 28 }}>
        같은 공모전 데이터·평가 기준을 쓰지만, 두 흐름은 서로 다른 경험을 제공합니다.
      </p>

      <div className="rb-grid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 32 }}>
        <div
          className="card glass"
          style={{ cursor: "pointer", border: mode === "pre" ? "1px solid var(--purple)" : "1px solid var(--glass-border)" }}
          onClick={() => setMode("pre")}
        >
          <Sparkles size={20} color="var(--purple)" />
          <div style={{ fontWeight: 700, fontSize: 15, margin: "10px 0 6px" }}>작성 전 → 주제 발굴</div>
          <div style={{ fontSize: 13, color: "var(--text-2)", lineHeight: 1.6 }}>
            아이디어가 아직 막연해요. 공모전 분석부터 AI 위원과 주제 회의까지.
          </div>
        </div>
        <div
          className="card glass"
          style={{ cursor: "pointer", border: mode === "post" ? "1px solid var(--coral)" : "1px solid var(--glass-border)" }}
          onClick={() => setMode("post")}
        >
          <FileText size={20} color="var(--coral)" />
          <div style={{ fontWeight: 700, fontSize: 15, margin: "10px 0 6px" }}>작성 후 → 문서 피드백</div>
          <div style={{ fontSize: 13, color: "var(--text-2)", lineHeight: 1.6 }}>
            기획서 초안 또는 완성본이 있어요. 바로 점수와 수정 우선순위를 확인.
          </div>
        </div>
      </div>

      <div className="card glass">
        <div style={{ fontSize: 13, color: "var(--text-1)", marginBottom: 10, display: "flex", alignItems: "center", gap: 6 }}>
          <Link2 size={14} /> 공모전 공고 · 평가기준
          <span className="badge amber mono" style={{ marginLeft: 6 }}>선택 입력</span>
        </div>

        <div style={{ display: "flex", gap: 4, background: "var(--bg-2)", borderRadius: 999, padding: 4, marginBottom: 14 }}>
          {[['url', 'URL 입력'], ['file', '파일 업로드']].map(([key, label]) => (
            <button
              key={key}
              onClick={() => setCriteriaTab(key)}
              style={{
                flex: 1, padding: '7px 0', borderRadius: 999, border: 'none', cursor: 'pointer',
                fontSize: 13, fontWeight: 600, fontFamily: 'inherit',
                background: criteriaTab === key ? 'var(--bg-1)' : 'transparent',
                color: criteriaTab === key ? 'var(--purple)' : 'var(--text-2)',
                boxShadow: criteriaTab === key ? '0 1px 4px rgba(28,26,46,0.1)' : 'none',
              }}
            >
              {label}
            </button>
          ))}
        </div>

        {criteriaTab === 'url' ? (
          <div style={{ display: "flex", gap: 10 }}>
            <input
              value={criteriaUrl}
              onChange={(e) => setCriteriaUrl(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleFetchCriteriaUrl()}
              placeholder="https://example.com/공고문"
              disabled={criteriaLoading}
              style={{ flex: 1, background: "var(--bg-1)", border: "1px solid var(--glass-border)", borderRadius: 10, padding: "11px 14px", color: "var(--text-0)", fontSize: 13 }}
            />
            <button className="btn-ghost" onClick={handleFetchCriteriaUrl} disabled={criteriaLoading}>
              {criteriaLoading ? '가져오는 중...' : '가져오기'}
            </button>
          </div>
        ) : (
          <div
            style={{
              border: `1.5px dashed ${isCriteriaDragging ? 'var(--purple)' : 'var(--glass-border)'}`,
              borderRadius: 12, padding: '18px 16px', display: 'flex', alignItems: 'center',
              justifyContent: 'space-between', background: isCriteriaDragging ? 'var(--purple-dim)' : 'var(--bg-1)',
            }}
            {...criteriaDropHandlers}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <Upload size={20} color="var(--purple)" />
              <div>
                <div style={{ fontSize: 14, fontWeight: 700 }}>{isCriteriaDragging ? '여기에 놓으세요' : '평가 기준 문서'}</div>
                <div style={{ fontSize: 12, color: 'var(--text-2)' }}>PDF, DOCX, PPTX, HWP, HWPX</div>
              </div>
            </div>
            <button className="btn-ghost" onClick={() => criteriaFileInputRef.current?.click()}>파일 선택</button>
            <input
              ref={criteriaFileInputRef}
              type="file"
              accept={ACCEPTED_DOCUMENT_EXTENSIONS.join(',')}
              multiple
              style={{ display: 'none' }}
              onChange={(e) => { addCriteriaFiles(e.target.files); e.target.value = ''; }}
            />
          </div>
        )}

        {criteriaError && <p style={{ color: "var(--coral)", fontSize: 13, marginTop: 12 }}>{criteriaError}</p>}

        {documents.length > 0 && (
          <div style={{ marginTop: 14 }}>
            {documents.map((doc, i) => (
              <div key={doc.id} style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                padding: '10px 0', borderTop: i > 0 ? '1px solid var(--glass-border)' : 'none',
              }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 13.5, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{doc.name}</div>
                  <div style={{ fontSize: 12, color: 'var(--text-2)' }}>{doc.meta}</div>
                </div>
                {doc.status === 'embedding' && <span className="badge amber mono" style={{ flexShrink: 0, marginLeft: 10 }}>색인 중</span>}
                {doc.status === 'done' && <span className="badge green mono" style={{ flexShrink: 0, marginLeft: 10 }}>✓ 완료</span>}
                {doc.status === 'warning' && <span className="badge amber mono" style={{ flexShrink: 0, marginLeft: 10 }}>확인 필요</span>}
                {doc.status === 'error' && <span className="badge coral mono" style={{ flexShrink: 0, marginLeft: 10 }}>실패</span>}
              </div>
            ))}
          </div>
        )}
      </div>

      {error && <p style={{ color: "var(--coral)", fontSize: 13, marginTop: 12 }}>{error}</p>}

      <button
        className="btn-primary"
        style={{ marginTop: 24, width: "100%", opacity: mode ? 1 : 0.4, display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}
        disabled={!mode || loading}
        onClick={() => onEnter(mode)}
      >
        {loading ? "준비하는 중..." : "분석 시작"} <ArrowRight size={15} />
      </button>
    </div>
  );
}

const _CONFIDENCE_LABEL = { high: '확신 높음', medium: '확신 보통', low: '확신 낮음' };

/* ---------------- 2. 공모전 분석 결과 (공통) ----------------
 * 가은/Claude(2026-07-21): 실측 제보 두 건에 대한 대응.
 * 1) "URL 넣고 분석 시작 눌렀는데 예시 카드만 나왔다" — 이 화면이 늘 고정 예시만
 *    보여줬던 문제. 이제 실제 수집한 공고문을 근거로 백엔드가 LLM 1회 호출로 뽑은
 *    official_facts(공고문에 실제 있는 사실)/strategic_analysis(AI 추론)를 보여준다.
 * 2) 팀 UX 스펙(2026-07-21) 그대로: 첫 화면은 4개 카드(핵심 과제/평가 갈리는 지점/
 *    반드시 지킬 조건/수상작 경향)만, 아래에 접을 수 있는 상세 분석(추천 전략/주의
 *    리스크/출처)을 둔다. 수상작·유사사례 경향은 이 시스템에 그 데이터 소스 자체가
 *    없어서 항상 "자료 미확보" 상태로 고정 표시하고 LLM이 지어내지 않는다.
 */
function AnalysisScreen({ mode, onNext, projectId }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [analysis, setAnalysis] = useState(null);
  const [detailOpen, setDetailOpen] = useState(false);

  useEffect(() => {
    if (!projectId) {
      setLoading(false);
      setAnalysis({ has_announcement: false });
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError('');
    getAnnouncementAnalysis(projectId)
      .then((data) => { if (!cancelled) setAnalysis(data); })
      .catch((err) => { if (!cancelled) setError(err.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [projectId]);

  if (loading) {
    return (
      <div style={{ maxWidth: 820 }}>
        <div className="badge purple mono">공고문 분석 중</div>
        <h1 style={{ fontSize: 26, fontWeight: 700, margin: "12px 0 24px" }}>등록한 공고문을 읽고 있어요...</h1>
        <div className="card glass" style={{ color: "var(--text-2)", fontSize: 13 }}>잠시만 기다려주세요.</div>
      </div>
    );
  }

  const hasAnnouncement = !!analysis?.has_announcement;
  const facts = analysis?.official_facts;
  const strategy = analysis?.strategic_analysis;
  const evidence = analysis?.evidence || [];

  const cards = hasAnnouncement
    ? [
        { icon: Target, color: "purple", title: "핵심 과제", body: strategy?.core_intent || "핵심 과제를 판단할 근거가 부족해요." },
        { icon: Award, color: "coral", title: "평가에서 갈리는 지점", list: facts?.evaluation_criteria },
        { icon: ShieldCheck, color: "green", title: "반드시 지켜야 할 조건", list: [...(facts?.eligibility || []), ...(facts?.submission_requirements || [])].slice(0, 4) },
        { icon: TrendingUp, color: "amber", title: "수상작·유사사례 경향", body: "수상작 자료 미확보 — 유사 공모전 사례 기반 분석은 아직 지원하지 않아요." },
      ]
    : [];

  return (
    <div style={{ maxWidth: 820 }}>
      <div className="badge purple mono">{hasAnnouncement ? "공고문 분석 결과" : "공고문 미등록"}</div>
      <h1 style={{ fontSize: 26, fontWeight: 700, margin: "12px 0 24px" }}>
        {hasAnnouncement ? (analysis?.announcement_title || "등록한 공고문을 확인하세요") : "등록된 공고문이 없어요"}
      </h1>

      {error && <p style={{ color: "var(--coral)", fontSize: 13, marginBottom: 16 }}>{error}</p>}

      {hasAnnouncement ? (
        <>
          <div className="rb-grid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 16 }}>
            {cards.map((it, i) => (
              <div key={i} className="card glass">
                <it.icon size={17} color={`var(--${it.color})`} />
                <div style={{ fontWeight: 600, fontSize: 13.5, margin: "10px 0 6px" }}>{it.title}</div>
                {it.body && <div style={{ fontSize: 12.5, color: "var(--text-2)", lineHeight: 1.6 }}>{it.body}</div>}
                {it.list && (
                  it.list.length > 0
                    ? <ul style={{ margin: 0, paddingLeft: 16, fontSize: 12.5, color: "var(--text-2)", lineHeight: 1.7 }}>
                        {it.list.map((v, j) => <li key={j}>{v}</li>)}
                      </ul>
                    : <div style={{ fontSize: 12.5, color: "var(--text-2)" }}>확인된 내용이 없어요.</div>
                )}
              </div>
            ))}
          </div>

          <button
            className="btn-ghost"
            style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 20 }}
            onClick={() => setDetailOpen((v) => !v)}
          >
            {detailOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            상세 분석 {detailOpen ? "접기" : "보기"}
          </button>

          {detailOpen && (
            <div style={{ display: "flex", flexDirection: "column", gap: 14, marginBottom: 24 }}>
              <div className="card glass">
                <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 10 }}>추천 전략</div>
                <ul style={{ margin: 0, paddingLeft: 16, fontSize: 12.5, color: "var(--text-1)", lineHeight: 1.8 }}>
                  {[...(strategy?.winning_points || []), ...(strategy?.recommended_direction || [])].map((v, i) => <li key={i}>{v}</li>)}
                  {(strategy?.winning_points?.length || 0) + (strategy?.recommended_direction?.length || 0) === 0 && (
                    <li style={{ color: "var(--text-2)" }}>제안할 전략을 판단할 근거가 부족해요.</li>
                  )}
                </ul>
              </div>

              <div className="card glass">
                <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 10 }}>주의 리스크</div>
                <ul style={{ margin: 0, paddingLeft: 16, fontSize: 12.5, color: "var(--text-1)", lineHeight: 1.8 }}>
                  {[...(strategy?.risk_flags || []), ...(facts?.disqualification_rules || [])].map((v, i) => <li key={i}>{v}</li>)}
                  {(strategy?.risk_flags?.length || 0) + (facts?.disqualification_rules?.length || 0) === 0 && (
                    <li style={{ color: "var(--text-2)" }}>공고문에 명시된 실격·주의 사항이 없어요.</li>
                  )}
                </ul>
                <div style={{ fontSize: 12, color: "var(--text-2)", marginTop: 10 }}>제출 마감: {facts?.deadline || "미공개"}</div>
              </div>

              <div className="card glass">
                <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 10 }}>출처</div>
                {evidence.length === 0 && <div style={{ fontSize: 12.5, color: "var(--text-2)" }}>표시할 근거가 없어요.</div>}
                {evidence.map((e, i) => (
                  <div key={i} style={{ padding: "8px 0", borderTop: i > 0 ? "1px solid var(--glass-border)" : "none" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "flex-start" }}>
                      <div style={{ fontSize: 12.5, color: "var(--text-1)" }}>{e.claim}</div>
                      <span className={`badge ${e.source_type === 'announcement' ? 'green' : 'purple'} mono`} style={{ flexShrink: 0 }}>
                        {e.source_type === 'announcement' ? '공고문 근거' : 'AI 추론'}
                      </span>
                    </div>
                    <div style={{ fontSize: 11, color: "var(--text-2)", marginTop: 2 }}>
                      {e.location || (e.source_type === 'announcement' ? '위치 미상' : '추론')} · {_CONFIDENCE_LABEL[e.confidence] || e.confidence}
                    </div>
                  </div>
                ))}
                {(analysis?.source_document_names?.length || 0) > 0 && (
                  <div style={{ fontSize: 11.5, color: "var(--text-2)", marginTop: 10 }}>
                    참고 문서: {analysis.source_document_names.join(', ')}
                  </div>
                )}
              </div>
            </div>
          )}
        </>
      ) : (
        <div className="card glass" style={{ borderColor: "var(--amber-dim)", marginBottom: 24 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
            <AlertCircle size={15} color="var(--amber)" style={{ marginTop: 2, flexShrink: 0 }} />
            <div style={{ fontSize: 12.5, color: "var(--text-1)", lineHeight: 1.6 }}>
              이전 화면에서 공고 URL이나 파일을 등록하지 않았어요 — 공식 심사기준 없이 일반적인 평가 관점으로 진행합니다.
            </div>
          </div>
        </div>
      )}

      <button className="btn-primary" style={{ display: "flex", alignItems: "center", gap: 8 }} onClick={onNext}>
        {mode === "pre" ? "AI 위원과 주제 확정 시작" : "기획서 업로드하기"} <ArrowRight size={15} />
      </button>
    </div>
  );
}

/* ---------------- 3. 작성 전: 주제 아이디어 회의 (더미) ---------------- */
function IdeationScreen({ onNext }) {
  const [messages, setMessages] = useState([
    { role: "ai", persona: "기획", text: "이 문제를 실제로 겪은 대상이 누구인가요?" },
  ]);
  const [draft, setDraft] = useState("");

  const send = () => {
    if (!draft.trim()) return;
    const next = [...messages, { role: "user", text: draft }];
    setMessages(next);
    setDraft("");
    // TODO(가은): 실제 주제 발굴 회의 API 붙이면 이 setTimeout을 대체
    setTimeout(() => {
      setMessages((cur) => [
        ...cur,
        { role: "ai", persona: "개발", text: "현재 보유한 기술·협력처·데이터 중 바로 활용 가능한 건 무엇인가요?" },
      ]);
    }, 400);
  };

  return (
    <div className="rb-grid-2" style={{ maxWidth: 860, display: "grid", gridTemplateColumns: "1fr 300px", gap: 20 }}>
      <div>
        <div className="badge coral mono" style={{ marginBottom: 10 }}>주제 아이디어 회의</div>
        <h2 style={{ fontSize: 20, fontWeight: 700, marginBottom: 16 }}>기획 위원 · 개발 위원과 함께 좁혀가는 중</h2>
        <div className="card glass" style={{ minHeight: 360, display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 12 }}>
            {messages.map((m, i) => (
              <div key={i} style={{ alignSelf: m.role === "ai" ? "flex-start" : "flex-end", maxWidth: "78%" }}>
                {m.role === "ai" && (
                  <div className={`badge ${m.persona === "기획" ? "purple" : "coral"} mono`} style={{ marginBottom: 4 }}>{m.persona} 위원</div>
                )}
                <div style={{
                  background: m.role === "ai" ? "var(--bg-1)" : "var(--purple-dim)",
                  border: "1px solid var(--glass-border)", borderRadius: 12, padding: "10px 14px", fontSize: 13.5, lineHeight: 1.6,
                }}>
                  {m.text}
                </div>
              </div>
            ))}
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()}
              placeholder="답변을 입력하세요"
              style={{ flex: 1, background: "var(--bg-1)", border: "1px solid var(--glass-border)", borderRadius: 10, padding: "10px 14px", color: "var(--text-0)", fontSize: 13 }}
            />
            <button className="btn-primary" style={{ padding: "10px 14px" }} onClick={send}><Send size={14} /></button>
          </div>
        </div>
      </div>

      <div>
        <div style={{ fontSize: 12, color: "var(--text-2)", marginBottom: 10, textTransform: "uppercase", letterSpacing: "0.05em" }}>주제 후보</div>
        {["예비창업인 재고관리 AI 비서", "무인매장 이상행동 감지"].map((t, i) => (
          <div key={i} className="card glass" style={{ marginBottom: 10, padding: 14 }}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>{t}</div>
            <div style={{ fontSize: 11.5, color: "var(--text-2)" }}>적합성 상 · 차별성 중 · 리스크 낮음</div>
          </div>
        ))}
        <button className="btn-ghost" style={{ width: "100%", marginTop: 8 }} onClick={onNext}>주제 확정하고 이어서 받기</button>
      </div>
    </div>
  );
}

/* ---------------- 4. 주제 확정 결과 (더미) ---------------- */
function IdeationResultScreen() {
  const rows = [
    ["문제 정의", "예비창업인의 87%가 재고 파악을 감으로 처리해 결품·과잉재고가 반복됨"],
    ["해결안", "POS 연동 재고 예측 AI 비서 → 판매 패턴 학습 후 발주 시점 자동 알림"],
    ["대상", "종업원 5인 이하 오프라인 소매업 예비창업인"],
    ["기대효과", "결품률 32% 감소, 재고 회전율 1.4배 개선 (유사 사례 기준 추정)"],
    ["검증 방법", "협력 매장 3곳 4주 파일럿, 발주 정확도·재고 회전율 비교"],
  ];
  return (
    <div style={{ maxWidth: 760 }}>
      <div className="badge green mono" style={{ marginBottom: 12 }}>주제 확정 · 기획서 작성 출발점</div>
      <h2 style={{ fontSize: 22, fontWeight: 700, marginBottom: 20 }}>예비창업인 재고관리 AI 비서</h2>
      <div className="card glass">
        {rows.map(([k, v], i) => (
          <div key={i} style={{ display: "grid", gridTemplateColumns: "110px 1fr", gap: 16, padding: "14px 0", borderTop: i > 0 ? "1px solid var(--glass-border)" : "none" }}>
            <div style={{ fontSize: 12, color: "var(--text-2)", fontFamily: "var(--mono)" }}>{k}</div>
            <div style={{ fontSize: 13.5, lineHeight: 1.6 }}>{v}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

const STAGE_STEPS = [
  { key: 'reviews', label: '멘토별 독립 검토' },
  { key: 'score', label: '채점 집계' },
  { key: 'chair', label: '위원장 종합' },
]

function overallPercent(snapshot) {
  if (!snapshot) return 0
  if (snapshot.chair_done) return 100
  if (snapshot.score_done) return 85
  if (snapshot.reviews_total) return 10 + (snapshot.reviews_done / snapshot.reviews_total) * 60
  return 5
}

function stageStatus(step, snapshot, mentorCount) {
  const reviewsDone = !!snapshot && snapshot.reviews_total > 0 && snapshot.reviews_done >= mentorCount
  if (step.key === 'reviews') return reviewsDone ? 'done' : (snapshot ? 'active' : 'pending')
  if (step.key === 'score') return snapshot?.score_done ? 'done' : (reviewsDone ? 'active' : 'pending')
  return snapshot?.chair_done ? 'done' : (snapshot?.score_done ? 'active' : 'pending')
}

/* ---------------- 5. 작성 후: 기획서 업로드 → 분석 시작 → 피드백 확인 (실제 API) ----------------
 * 가은/Claude(2026-07-20): 평가 대상 문서 업로드는 DocumentUploadPage.jsx(/projects/new)의
 * uploadDocument(pid, file, 'pdf', 'target') 로직을 그대로 재사용한다. "분석 시작"은
 * MentorSelectionPage.jsx가 하던 getMentorCandidates → analyzeProject → getAnalyzeProgress
 * 폴링을 그대로 쓰되, 멘토 선택 화면 없이 추천 후보를 전부(최대 4명) 자동 선택한다.
 */
function UploadAndAnalyzeScreen({ projectId, onFeedbackReady }) {
  const [documents, setDocuments] = useState([])
  const [isDragging, setIsDragging] = useState(false)
  const [fileError, setFileError] = useState('')
  const fileInputRef = useRef(null)

  const [candidatesError, setCandidatesError] = useState('')
  const [analyzing, setAnalyzing] = useState(false)
  const [snapshot, setSnapshot] = useState(null)
  const [mentorCount, setMentorCount] = useState(0)
  const [reviewsReady, setReviewsReady] = useState(false)
  const progressTokenRef = useRef(null)
  const pollTimerRef = useRef(null)

  // 가은/Claude(2026-07-20): 실측 버그 — 분석 진행 중에 사이드바로 다른 단계로 이동하면
  // (unmount) 이 interval이 안 멈추고 계속 살아서 백엔드를 계속 두드렸다
  // (MentorSelectionPage.jsx에는 있던 언마운트 정리를 포팅하면서 빠뜨림).
  useEffect(() => {
    return () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current)
        pollTimerRef.current = null
      }
    }
  }, [])

  function updateDoc(id, patch) {
    setDocuments((prev) => prev.map((doc) => (doc.id === id ? { ...doc, ...patch } : doc)))
  }

  async function uploadOne(file) {
    const id = `${file.name}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
    setDocuments((prev) => [...prev, { id, name: file.name, meta: formatFileSize(file.size), status: 'uploading' }])
    try {
      const doc = await uploadDocument(projectId, file, 'pdf', 'target')
      if (doc.status === 'conversion_failed') {
        updateDoc(id, { status: 'error', meta: doc.conversion_metadata?.conversion_error || '문서를 변환하지 못했습니다.' })
        return
      }
      updateDoc(id, { status: 'done' })
    } catch (err) {
      updateDoc(id, { status: 'error', meta: err.message })
    }
  }

  function addFiles(fileList) {
    const files = Array.from(fileList)
    const accepted = files.filter(isAcceptedDocument)
    const rejected = files.length - accepted.length
    setFileError(rejected > 0 ? 'PDF, DOCX, PPTX, HWP, HWPX 파일만 업로드할 수 있습니다.' : '')
    accepted.forEach(uploadOne)
  }

  const dropHandlers = {
    onDragOver: (e) => { e.preventDefault(); setIsDragging(true) },
    onDragLeave: (e) => { e.preventDefault(); setIsDragging(false) },
    onDrop: (e) => { e.preventDefault(); setIsDragging(false); addFiles(e.dataTransfer.files) },
  }

  const hasReadyDocument = documents.some((d) => d.status === 'done')

  // 가은/Claude(2026-07-20): "멘토링선택xx" — MentorSelectionPage의 후보 카드 선택 UI 없이,
  // getMentorCandidates()가 추천한 후보를 순서대로 최대 4명까지 자동으로 그대로 쓴다.
  async function handleStartAnalyze() {
    if (analyzing) return
    setCandidatesError('')
    setAnalyzing(true)
    try {
      const data = await getMentorCandidates(projectId)
      const autoSelected = data.candidates.slice(0, MAX_MENTORS).map((c) => c.persona_id)
      if (autoSelected.length < MIN_MENTORS) {
        throw new Error('추천 멘토가 충분하지 않습니다.')
      }
      setMentorCount(autoSelected.length)

      progressTokenRef.current =
        typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`
      const progressToken = progressTokenRef.current

      pollTimerRef.current = setInterval(() => {
        getAnalyzeProgress(projectId, progressToken).then((snap) => {
          if (!snap) return
          setSnapshot(snap)
          if (snap.chair_done && pollTimerRef.current) {
            clearInterval(pollTimerRef.current)
            pollTimerRef.current = null
          }
        })
      }, ANALYZE_POLL_INTERVAL_MS)

      const result = await analyzeProject(projectId, autoSelected, progressToken)
      sessionStorage.setItem(`analysis:${projectId}`, JSON.stringify(result))
      setReviewsReady(true)
    } catch (err) {
      setCandidatesError(err.message)
      setAnalyzing(false)
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current)
        pollTimerRef.current = null
      }
    }
  }

  const reviewsDone = !!snapshot && snapshot.reviews_total > 0 && snapshot.reviews_done >= mentorCount
  const analyzePercent = overallPercent(snapshot)

  return (
    <div style={{ maxWidth: 720 }}>
      <div className="badge coral mono" style={{ marginBottom: 12 }}>기획서 업로드 · 분석</div>
      <h2 style={{ fontSize: 22, fontWeight: 700, marginBottom: 20 }}>평가 대상 문서를 업로드하세요</h2>

      {!analyzing && (
        <>
          <div
            className="card glass"
            style={{
              borderStyle: 'dashed',
              borderColor: isDragging ? 'var(--coral)' : 'var(--glass-border)',
              padding: 40, textAlign: 'center',
            }}
            {...dropHandlers}
          >
            <Upload size={26} color="var(--coral)" style={{ marginBottom: 14 }} />
            <div style={{ fontWeight: 600, marginBottom: 6 }}>{isDragging ? '여기에 놓으세요' : '기획서를 업로드하세요'}</div>
            <div style={{ fontSize: 12.5, color: 'var(--text-2)', marginBottom: 20 }}>PDF, DOCX, PPTX, HWP, HWPX</div>
            <button className="btn-primary" onClick={() => fileInputRef.current?.click()}>파일 선택</button>
            <input
              ref={fileInputRef}
              type="file"
              accept={ACCEPTED_DOCUMENT_EXTENSIONS.join(',')}
              multiple
              style={{ display: 'none' }}
              onChange={(e) => { addFiles(e.target.files); e.target.value = '' }}
            />
          </div>

          {fileError && <p style={{ color: 'var(--coral)', fontSize: 13, marginTop: 12 }}>{fileError}</p>}

          {documents.length > 0 && (
            <div className="card glass" style={{ marginTop: 16 }}>
              {documents.map((doc, i) => (
                <div key={doc.id} style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  padding: '10px 0', borderTop: i > 0 ? '1px solid var(--glass-border)' : 'none',
                }}>
                  <div>
                    <div style={{ fontSize: 13.5, fontWeight: 600 }}>{doc.name}</div>
                    <div style={{ fontSize: 12, color: 'var(--text-2)' }}>{doc.meta}</div>
                  </div>
                  {doc.status === 'uploading' && <span className="badge amber mono">업로드 중</span>}
                  {doc.status === 'done' && <span className="badge green mono">✓ 완료</span>}
                  {doc.status === 'error' && <span className="badge coral mono">실패</span>}
                </div>
              ))}
            </div>
          )}

          {candidatesError && <p style={{ color: 'var(--coral)', fontSize: 13, marginTop: 12 }}>{candidatesError}</p>}

          <button
            className="btn-primary"
            style={{ marginTop: 24, width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}
            disabled={!hasReadyDocument}
            onClick={handleStartAnalyze}
          >
            분석 시작 <ArrowRight size={15} />
          </button>
          {!hasReadyDocument && <p style={{ fontSize: 12, color: 'var(--text-2)', textAlign: 'center', marginTop: 8 }}>문서 업로드가 끝나면 분석을 시작할 수 있어요.</p>}
        </>
      )}

      {analyzing && (
        <div className="card glass">
          <p style={{ fontSize: 13, color: 'var(--text-1)', marginBottom: 16 }}>
            {mentorCount > 0
              ? `추천 위원 ${mentorCount}명이 기획서를 바탕으로 독립적으로 피드백을 준비하고 있어요.`
              : '어울리는 위원을 찾는 중이에요...'}
          </p>
          <div className="progress-track" style={{ marginBottom: 6 }}>
            <div className="progress-fill" style={{ width: `${analyzePercent}%` }} />
          </div>
          <p style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 20 }}>{Math.round(analyzePercent)}%</p>

          <div style={{ display: 'flex', gap: 18, marginBottom: 8 }}>
            {STAGE_STEPS.map((step) => {
              const status = stageStatus(step, snapshot, mentorCount)
              return (
                <div key={step.key} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12.5 }}>
                  {status === 'done'
                    ? <CheckCircle2 size={15} color="var(--green)" />
                    : <Circle size={13} color={status === 'active' ? 'var(--purple)' : 'var(--text-2)'} />}
                  <span style={{ color: status === 'pending' ? 'var(--text-2)' : 'var(--text-0)' }}>{step.label}</span>
                </div>
              )
            })}
          </div>

          {!reviewsReady && (
            <p style={{ fontSize: 12.5, color: 'var(--text-2)', marginTop: 16 }}>⏱ 평균 검토 시간 약 3~5분 · 잠시만 기다려주세요</p>
          )}

          {reviewsReady && (
            <>
              <p style={{ fontSize: 12.5, color: 'var(--text-2)', marginTop: 16, marginBottom: 16 }}>
                위원들의 검토가 끝났어요. 위원장 종합은 백그라운드에서 계속 진행돼요 — 대화 중 필요할 때 참고할게요.
              </p>
              <button className="btn-primary" style={{ width: '100%' }} onClick={() => onFeedbackReady(projectId)}>
                피드백 확인하기 →
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

/* ---------------------------- 페이지 진입점 ---------------------------- */
export default function ReviewBoardPrototype() {
  const navigate = useNavigate();
  const [mode, setMode] = useState(null);
  const [stage, setStage] = useState("entry");
  const [projectId, setProjectId] = useState(null);
  const [entryLoading, setEntryLoading] = useState(false);
  const [entryError, setEntryError] = useState('');
  // 가은/Claude(2026-07-20): 실측 버그 — URL로 실제 공고문을 수집해도 "공모전 분석"
  // 화면엔 항상 똑같은 고정 예시 카드만 나왔다(EntryScreen이 모은 문서 목록이 어디에도
  // 안 넘어갔음). AnalysisScreen에서 보여줄 수 있게 여기(부모)로 끌어올린다.
  const [criteriaDocuments, setCriteriaDocuments] = useState([]);

  const goNext = () => {
    const seq = (mode && FLOW_BY_MODE[mode]) || ["entry"];
    const i = seq.indexOf(stage);
    if (i < seq.length - 1) setStage(seq[i + 1]);
  };

  // 가은/Claude(2026-07-20): projectId가 아직 없으면(공고 URL/파일을 하나도 안 넣고
  // 바로 "분석 시작"을 눌렀거나, EntryScreen의 URL/파일 액션이 이미 만들어뒀거나) 여기서
  // 한 번 더 보장한다 — DocumentUploadPage.jsx의 ensureProject()와 동일한 "지연 생성"
  // 패턴이라 URL/파일을 여러 번 넣어도 프로젝트가 중복 생성되지 않는다.
  const projectIdRef = useRef(null);
  projectIdRef.current = projectId;
  async function ensureProject() {
    if (projectIdRef.current) return projectIdRef.current;
    const project = await createProject({ title: "새 공모전 프로젝트", doc_type: "competition" });
    projectIdRef.current = project.id;
    setProjectId(project.id);
    return project.id;
  }

  async function handleEnter(m) {
    setMode(m);
    if (m !== "post") {
      setStage("analysis");
      return;
    }
    setEntryError("");
    setEntryLoading(true);
    try {
      await ensureProject();
      setStage("analysis");
    } catch (err) {
      setEntryError(err.message);
    } finally {
      setEntryLoading(false);
    }
  }

  function handleFeedbackReady(pid) {
    navigate(`/projects/${pid}/feedback-chat`);
  }

  return (
    <Shell active={stage} mode={mode} onNavigate={setStage} showNav={stage !== "entry"}>
      {stage === "entry" && (
        <EntryScreen
          onEnter={handleEnter}
          loading={entryLoading}
          error={entryError}
          projectId={projectId}
          ensureProject={ensureProject}
          documents={criteriaDocuments}
          setDocuments={setCriteriaDocuments}
        />
      )}
      {stage === "analysis" && (
        <AnalysisScreen mode={mode} onNext={goNext} projectId={projectId} />
      )}
      {stage === "ideation" && <IdeationScreen onNext={goNext} />}
      {stage === "ideation_result" && <IdeationResultScreen />}
      {stage === "upload" && (
        <UploadAndAnalyzeScreen projectId={projectId} onFeedbackReady={handleFeedbackReady} />
      )}
    </Shell>
  );
}
