import { useEffect, useRef, useState, type ReactNode } from "react";
import { registerWorkspaceTools } from "./webmcp";
import ReviewDisposition, { ReviewStatus } from "./ReviewDisposition";
import PatchCoreDiagnosis, {
  detectorNeedsReview,
  detectorSummary,
} from "./PatchCoreDiagnosis";
import {
  ScanLine,
  FlaskConical,
  History,
  Upload,
  ArrowRight,
  CheckCircle2,
  AlertTriangle,
  CircleHelp,
  XCircle,
  ZoomIn,
  ZoomOut,
  RotateCcw,
  Download,
  Layers,
  Play,
  Square,
  Settings2,
  FileImage,
  ChevronRight,
} from "lucide-react";

type Data = Record<string, any>;
type Page = "inspect" | "experiments" | "history";
const METHODS: Record<string, string> = {
  vlm_only: "A · VLM 단독",
  vlm_reference: "B · 정상 참조 + VLM",
  patchcore: "C · PatchCore",
  patchcore_vlm: "D · PatchCore + VLM",
};
const METHOD_DESCRIPTIONS: Record<string, string> = {
  vlm_only: "검사 이미지 한 장을 보고 관찰 가능한 외관 상태를 확인합니다.",
  vlm_reference: "정상 참조와 비교하는 VLM 기반 이상탐지입니다.",
  patchcore: "정상 제품의 특징과 비교한 이상 점수와 의심 영역을 확인합니다.",
  patchcore_vlm:
    "정상 참조와 확대된 의심 영역을 함께 보고 두 모델의 판정을 확인합니다.",
};
const usesReference = (value: string) =>
  ["vlm_reference", "patchcore_vlm"].includes(value);
const usesDetector = (value: string) =>
  ["patchcore", "patchcore_vlm"].includes(value);
const imageRoles = (value: string) =>
  value === "vlm_only"
    ? "검사 이미지"
    : value === "vlm_reference"
      ? "검사·정상 참조 이미지"
      : "검사·정상 참조·의심 영역 이미지";
const DECISIONS: Record<string, string> = {
  normal: "정상",
  defect_suspected: "불량 의심",
  uncertain: "판단 보류",
  failed: "실행 실패",
};
async function api<T = Data>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch("/api" + path, init);
  const v = await r.json();
  if (!r.ok)
    throw new Error(
      typeof v.detail === "string" ? v.detail : JSON.stringify(v.detail),
    );
  return v;
}
const post = (body?: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body ?? {}),
});
function downloadJSON(value: unknown, name: string) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}
function Badge({ decision }: { decision: string | null }) {
  const Icon =
    decision === "normal"
      ? CheckCircle2
      : decision === "defect_suspected"
        ? AlertTriangle
        : decision === "failed"
          ? XCircle
          : CircleHelp;
  return (
    <span className={"badge " + (decision ?? "pending")}>
      <Icon size={15} />
      {decision ? (DECISIONS[decision] ?? decision) : "미측정"}
    </span>
  );
}
function Metric({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value == null ? "미측정" : String(value)}</strong>
    </div>
  );
}
const rate = (v: Data | undefined) =>
  v?.value == null ? "N/A" : (v.value * 100).toFixed(1) + "%";

function ImageViewer({
  title,
  subtitle,
  src,
  record,
  reference = false,
  onFilesDrop,
  uploading = false,
  dropDisabled = false,
  uploadHint,
  action,
}: {
  title: string;
  subtitle: string;
  src?: string;
  record?: Data;
  reference?: boolean;
  onFilesDrop?: (files: File[]) => void;
  uploading?: boolean;
  dropDisabled?: boolean;
  uploadHint?: string;
  action?: ReactNode;
}) {
  const [scale, setScale] = useState(1),
    [pos, setPos] = useState({ x: 0, y: 0 }),
    [heat, setHeat] = useState(false),
    [boxes, setBoxes] = useState(true),
    [dragOver, setDragOver] = useState(false);
  const dragDepth = useRef(0);
  const drag = useRef<{ x: number; y: number; px: number; py: number } | null>(
    null,
  );
  useEffect(() => {
    setScale(1);
    setPos({ x: 0, y: 0 });
    setHeat(false);
  }, [src]);
  const rois = record?.roi ?? [];
  return (
    <section
      className={"viewer" + (dragOver ? " file-drag-over" : "")}
      aria-busy={uploading}
      onDragEnter={(e) => {
        if (!onFilesDrop || !e.dataTransfer.types.includes("Files")) return;
        e.preventDefault();
        e.stopPropagation();
        dragDepth.current += 1;
        setDragOver(true);
      }}
      onDragOver={(e) => {
        if (!onFilesDrop || !e.dataTransfer.types.includes("Files")) return;
        e.preventDefault();
        e.stopPropagation();
        e.dataTransfer.dropEffect = dropDisabled ? "none" : "copy";
      }}
      onDragLeave={(e) => {
        if (!onFilesDrop) return;
        dragDepth.current = Math.max(0, dragDepth.current - 1);
        if (dragDepth.current === 0) setDragOver(false);
      }}
      onDrop={(e) => {
        if (!onFilesDrop || !e.dataTransfer.types.includes("Files")) return;
        e.preventDefault();
        e.stopPropagation();
        dragDepth.current = 0;
        setDragOver(false);
        onFilesDrop(Array.from(e.dataTransfer.files));
      }}
    >
      <div className="panel-heading">
        <div>
          <span className="eyebrow">{reference ? "REFERENCE" : "QUERY"}</span>
          <h3>{title}</h3>
        </div>
        <span className="subtle">{subtitle}</span>
      </div>
      <div
        className="image-stage"
        tabIndex={0}
        aria-label={
          title +
          " 이미지, 확대 후 드래그하여 이동" +
          (onFilesDrop ? ". 이미지 파일을 끌어다 놓아 업로드" : "")
        }
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            setScale(1);
            setPos({ x: 0, y: 0 });
          }
        }}
        onPointerDown={(e) => {
          if (scale > 1) {
            drag.current = { x: e.clientX, y: e.clientY, px: pos.x, py: pos.y };
            e.currentTarget.setPointerCapture(e.pointerId);
          }
        }}
        onPointerMove={(e) => {
          if (drag.current)
            setPos({
              x: drag.current.px + e.clientX - drag.current.x,
              y: drag.current.py + e.clientY - drag.current.y,
            });
        }}
        onPointerUp={() => (drag.current = null)}
        onPointerCancel={() => (drag.current = null)}
      >
        {src ? (
          <div
            className="image-transform"
            style={{
              transform: `translate(${pos.x}px,${pos.y}px) scale(${scale})`,
            }}
          >
            <img src={src} alt={title} draggable={false} />
            {heat && record?.heatmap_file && (
              <img
                className="heatmap"
                src={`/api/inspections/${record.inspection_id}/heatmap`}
                alt="정상 calibration 기준 고정 색상 범위의 PatchCore 이상 지도"
              />
            )}
            {boxes && rois.length > 0 && (
              <svg
                className="roi-overlay"
                viewBox={`0 0 ${record?.image_width} ${record?.image_height}`}
                aria-label="검토 후보 영역"
              >
                {rois.map((r: Data, i: number) => (
                  <rect
                    key={i}
                    x={r.box[0]}
                    y={r.box[1]}
                    width={r.box[2] - r.box[0]}
                    height={r.box[3] - r.box[1]}
                    fill="none"
                    stroke="#f59e0b"
                    strokeWidth="3"
                    vectorEffect="non-scaling-stroke"
                  />
                ))}
              </svg>
            )}
          </div>
        ) : (
          <div className="image-empty">
            <FileImage size={36} strokeWidth={1.2} />
            <strong>
              {reference
                ? "정상 참조가 아직 없습니다"
                : "검사할 이미지를 끌어다 놓으세요"}
            </strong>
            <span>
              {reference
                ? "데이터 설치 후 fit_normal에서 고정 선택됩니다."
                : "PNG · JPG · WEBP / 최대 10MB"}
            </span>
          </div>
        )}
        {(dragOver || uploading) && (
          <div className="file-drop-overlay" role="status" aria-live="polite">
            {uploading ? <span className="spinner" /> : <Upload size={32} />}
            <strong>
              {uploading
                ? "이미지 업로드 중…"
                : dropDisabled
                  ? uploadHint
                  : "여기에 놓으면 검사 이미지가 올라갑니다"}
            </strong>
            {!uploading && !dropDisabled && (
              <span>PNG · JPG · WEBP 한 장 / 최대 10MB</span>
            )}
          </div>
        )}
      </div>
      {onFilesDrop && (
        <p className="file-drop-hint">
          <Upload size={15} />
          {uploadHint ??
            "이미지 파일을 끌어다 놓거나 ‘이미지 업로드’를 누르세요."}
        </p>
      )}
      <div className="viewer-tools">
        <span>{src ? "원본 비율 유지" : "이미지 대기"}</span>
        <div>
          <button
            aria-label="축소"
            onClick={() => setScale(Math.max(1, scale - 0.5))}
          >
            <ZoomOut size={17} />
          </button>
          <span>{Math.round(scale * 100)}%</span>
          <button
            aria-label="확대"
            onClick={() => setScale(Math.min(5, scale + 0.5))}
          >
            <ZoomIn size={17} />
          </button>
          <button
            aria-label="이미지 보기 초기화"
            onClick={() => {
              setScale(1);
              setPos({ x: 0, y: 0 });
            }}
          >
            <RotateCcw size={16} />
          </button>
        </div>
      </div>
      {record?.heatmap_file && (
        <div className="overlay-options">
          <label>
            <input
              type="checkbox"
              checked={heat}
              onChange={(e) => setHeat(e.target.checked)}
            />{" "}
            이상 지도
          </label>
          <label>
            <input
              type="checkbox"
              checked={boxes}
              onChange={(e) => setBoxes(e.target.checked)}
            />{" "}
            검토 후보 {rois.length}개
          </label>
          <small>PatchCore 결과 · VLM의 픽셀 예측 아님</small>
        </div>
      )}
      {action}
    </section>
  );
}

export default function App() {
  const [page, setPage] = useState<Page>("inspect"),
    [status, setStatus] = useState<Data | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [loadingResult, setLoadingResult] = useState(false),
    [uploading, setUploading] = useState(false);
  const [mode, setMode] = useState("openai"),
    [method, setMethod] = useState("vlm_reference"),
    [asset, setAsset] = useState<Data | null>(null),
    [refs, setRefs] = useState<Data[]>([]),
    [consent, setConsent] = useState(false),
    [result, setResult] = useState<Data | null>(null);
  const [history, setHistory] = useState<Data[]>([]),
    [filter, setFilter] = useState({
      method: "",
      decision: "",
      status: "",
      date: "",
      category: "",
    }),
    [note, setNote] = useState(""),
    [reviewStatus, setReviewStatus] = useState("unreviewed"),
    [reviewChecks, setReviewChecks] = useState<Data>({});
  const [question, setQuestion] = useState(""),
    [answer, setAnswer] = useState<Data | null>(null),
    [questionBusy, setQuestionBusy] = useState(false);
  useEffect(() => {
    setReviewStatus(result?.human_review_status ?? "unreviewed");
    setNote(result?.human_review?.note ?? "");
    setReviewChecks(result?.human_review ?? {});
  }, [result?.inspection_id]);
  const [expConsent, setExpConsent] = useState(false);
  const [expMethods, setExpMethods] = useState(["vlm_only", "vlm_reference"]),
    [sampleLimit, setSampleLimit] = useState(10),
    [full, setFull] = useState(false),
    [exploratory, setExploratory] = useState(true),
    [preview, setPreview] = useState<Data | null>(null),
    [experiment, setExperiment] = useState<Data | null>(null),
    [experiments, setExperiments] = useState<Data[]>([]),
    [cases, setCases] = useState<Data[]>([]),
    [caseFilter, setCaseFilter] = useState("all");
  const uploadRef = useRef<HTMLInputElement>(null),
    abortRef = useRef<AbortController | null>(null),
    uploadLock = useRef(false),
    resultLoadLock = useRef(false),
    initialMethodSet = useRef(false);
  const loadStatus = () =>
    api("/status")
      .then(setStatus)
      .catch((e) => setError("백엔드 연결 실패: " + e.message));
  useEffect(() => {
    loadStatus();
    return registerWorkspaceTools(setPage);
  }, []);
  useEffect(() => {
    if (!status || initialMethodSet.current) return;
    initialMethodSet.current = true;
    if (
      mode === "openai" &&
      status.detector_ready &&
      (!status.api_key_configured || !status.external_api_enabled)
    )
      setMethod("patchcore");
  }, [status, mode]);
  useEffect(() => {
    // File drops outside the query viewer must not replace the app with a file.
    const preventFileNavigation = (event: DragEvent) => {
      if (event.dataTransfer?.types.includes("Files")) {
        event.preventDefault();
        event.dataTransfer.dropEffect = "none";
      }
    };
    window.addEventListener("dragover", preventFileNavigation);
    window.addEventListener("drop", preventFileNavigation);
    return () => {
      window.removeEventListener("dragover", preventFileNavigation);
      window.removeEventListener("drop", preventFileNavigation);
    };
  }, []);
  useEffect(() => {
    let cancelled = false;
    if (
      page === "inspect" &&
      status?.data_ready &&
      mode === "openai" &&
      usesReference(method)
    )
      api<Data[]>("/references/" + status.category)
        .then((value) => {
          if (!cancelled) setRefs(value);
        })
        .catch((e) => {
          if (!cancelled) setError(e.message);
        });
    else setRefs([]);
    return () => {
      cancelled = true;
    };
  }, [status?.data_ready, status?.category, mode, method, page]);
  useEffect(() => {
    if (page === "history")
      api<Data[]>(
        "/inspections?" +
          new URLSearchParams(
            Object.fromEntries(
              Object.entries(filter).filter(([k, v]) => k !== "date" && v),
            ),
          ),
      )
        .then(setHistory)
        .catch((e) => setError(e.message));
    if (page === "experiments")
      api<Data[]>("/experiments")
        .then(setExperiments)
        .catch((e) => setError(e.message));
  }, [page, filter]);
  useEffect(() => {
    if (!experiment || experiment.status !== "running") return;
    const id = setInterval(
      () =>
        api("/experiments/" + experiment.experiment_id)
          .then((v) => {
            setExperiment(v);
            if (v.status !== "running") loadStatus();
          })
          .catch((e) => setError(e.message)),
      1200,
    );
    return () => clearInterval(id);
  }, [experiment?.experiment_id, experiment?.status]);
  useEffect(() => {
    setPreview(null);
  }, [expMethods, sampleLimit, full, exploratory]);
  useEffect(() => {
    if (experiment && ["completed", "cancelled"].includes(experiment.status))
      api<Data[]>("/experiments/" + experiment.experiment_id + "/cases")
        .then(setCases)
        .catch((e) => setError(e.message));
    else setCases([]);
  }, [experiment?.experiment_id, experiment?.status]);
  function uploadFiles(files: File[]) {
    if (mode === "demo") {
      setError("제품 사진을 올리려면 실행 모드를 ‘실제 모델’로 바꿔주세요.");
      return;
    }
    if (busy || questionBusy || uploadLock.current || resultLoadLock.current) {
      setError("진행 중인 작업이 끝난 뒤 이미지를 바꿔주세요.");
      return;
    }
    if (files.length !== 1) {
      setError("검사할 이미지 파일을 한 장씩 올려주세요.");
      return;
    }
    const file = files[0];
    const supported = file.type
      ? ["image/png", "image/jpeg", "image/webp"].includes(file.type)
      : /\.(png|jpe?g|webp)$/i.test(file.name);
    if (!supported) {
      setError("PNG, JPG, WEBP 이미지 파일만 올릴 수 있습니다.");
      return;
    }
    if (!file.size || file.size > 10 * 1024 * 1024) {
      setError("비어 있지 않은 10MB 이하의 이미지 파일을 올려주세요.");
      return;
    }
    void upload(file);
  }
  async function upload(file: File) {
    uploadLock.current = true;
    setUploading(true);
    setError("");
    setConsent(false);
    const form = new FormData();
    form.append("file", file);
    try {
      setAsset(await api("/assets", { method: "POST", body: form }));
      setConsent(false);
      setResult(null);
      setAnswer(null);
    } catch (e) {
      setError(String(e));
    } finally {
      uploadLock.current = false;
      setUploading(false);
    }
  }
  async function demo() {
    try {
      setMode("demo");
      setConsent(false);
      setAsset(await api("/demo/sample", post()));
      setResult(null);
      setAnswer(null);
    } catch (e) {
      setError(String(e));
    }
  }
  async function inspect() {
    if (!asset || uploadLock.current || runDisabledReason) return;
    setBusy(true);
    setError("");
    setResult(null);
    setAnswer(null);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const r = await api("/inspections", {
        ...post({
          asset_id: asset.asset_id,
          category: status?.category ?? "metal_nut",
          method,
          provider: mode,
          external_consent: consent,
          use_cache: true,
        }),
        signal: controller.signal,
      });
      setResult(r);
      if (r.execution_status === "failed") setError(r.error_message);
    } catch (e) {
      setError(
        controller.signal.aborted
          ? "화면 대기를 취소했습니다. 이미 전송한 검사는 완료 후 이력에 저장됩니다."
          : String(e),
      );
    } finally {
      setBusy(false);
      loadStatus();
    }
  }
  async function ask() {
    if (
      !result ||
      !question.trim() ||
      busy ||
      resultLoadLock.current ||
      uploadLock.current ||
      questionBusy
    )
      return;
    setQuestionBusy(true);
    try {
      setAnswer(
        await api(
          `/inspections/${result.inspection_id}/questions`,
          post({ question, external_consent: consent }),
        ),
      );
    } catch (e) {
      setError(String(e));
    } finally {
      setQuestionBusy(false);
      loadStatus();
    }
  }
  const category = status?.category ?? "metal_nut";
  const experimentRequest = {
    category,
    methods: expMethods,
    sample_limit: sampleLimit,
    full_evaluation: full,
    exploratory,
    external_consent: expConsent,
    use_cache: false,
  };
  const needsDetector = usesDetector(method);
  const needsReference = usesReference(method);
  const showReference = needsReference && mode !== "demo";
  const resultUsesVlm =
    result && result.method !== "patchcore" && !result.is_demo;
  const showFollowup = resultUsesVlm && result.execution_status === "succeeded";
  const experimentUsesVlm = expMethods.some((value) => value !== "patchcore");
  const experimentUsesReference = expMethods.some(usesReference);
  const setupBlockedReason =
    mode === "demo"
      ? needsDetector
        ? "데모에서는 A 또는 B 방식을 선택하세요."
        : null
      : !status
        ? "서버 연결 상태를 확인하고 있습니다."
        : needsDetector && !status.detector_ready
          ? "이 방식은 정상 이미지로 PatchCore를 먼저 준비해야 합니다."
          : needsReference && !status.data_ready
            ? "정상 참조 데이터가 필요합니다. 데이터셋을 먼저 등록하세요."
            : method !== "patchcore" && !status.external_api_enabled
              ? `${METHODS[method]}는 외부 VLM 호출 허용 설정이 필요합니다.`
              : method !== "patchcore" && !status.api_key_configured
                ? `${METHODS[method]}는 서버 API 키 설정이 필요합니다.`
                : method !== "patchcore" && !consent
                  ? "이미지 전송·유료 호출 동의에 체크해야 검사할 수 있습니다."
                  : null;
  const runDisabledReason = loadingResult
    ? "검사 기록을 불러오고 있습니다."
    : uploading
      ? "이미지를 업로드하고 있습니다."
      : busy
        ? "검사가 진행 중입니다."
        : questionBusy
          ? "후속 질문의 응답을 기다리고 있습니다."
          : !asset
            ? mode === "demo"
              ? "데모 샘플을 먼저 불러오세요."
              : "검사할 이미지를 먼저 올려주세요."
            : setupBlockedReason;
  const canSwitchToLocal =
    mode === "openai" &&
    method !== "patchcore" &&
    status?.detector_ready &&
    setupBlockedReason &&
    !busy &&
    !uploading &&
    !questionBusy;
  function selectMethod(value: string) {
    if (resultLoadLock.current) return;
    initialMethodSet.current = true;
    setMethod(value);
    setResult(null);
    setAnswer(null);
  }
  const selectedRefs = result?.reference_assets ?? refs;
  async function openResult(snapshot: Data) {
    if (busy || questionBusy || uploadLock.current || resultLoadLock.current) {
      setError("진행 중인 작업이 끝난 뒤 다른 검사 결과를 열어주세요.");
      return;
    }
    resultLoadLock.current = true;
    setLoadingResult(true);
    try {
      // Experiment cases preserve their original predictions; details use the latest review record.
      const r = await api(`/inspections/${snapshot.inspection_id}`);
      initialMethodSet.current = true;
      setResult(r);
      setAsset({
        asset_id: r.asset_id,
        url: r.image_url,
        width: r.image_width,
        height: r.image_height,
      });
      setMode(r.is_demo ? "demo" : "openai");
      setMethod(r.method);
      setNote(r.human_review?.note ?? "");
      setReviewChecks(r.human_review ?? {});
      setReviewStatus(r.human_review_status ?? "unreviewed");
      setAnswer(null);
      setConsent(false);
      setPage("inspect");
    } catch (e) {
      setError(String(e));
    } finally {
      resultLoadLock.current = false;
      setLoadingResult(false);
    }
  }
  const filteredCases = cases.filter(
    (r) =>
      caseFilter === "all" ||
      (caseFilter === "false_negative" &&
        r.truth === "defect" &&
        r.final_decision === "normal") ||
      (caseFilter === "false_positive" &&
        r.truth === "normal" &&
        r.final_decision === "defect_suspected") ||
      (caseFilter === "uncertain" && r.final_decision === "uncertain") ||
      (caseFilter === "failed" && r.execution_status === "failed"),
  );
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setPage("inspect");
          }}
        >
          InspectMate.
        </a>
        <nav>
          {(
            [
              ["inspect", "검사", ScanLine],
              ["experiments", "비교 실험", FlaskConical],
              ["history", "검사 이력", History],
            ] as const
          ).map(([key, label, Icon]) => (
            <button
              key={key}
              className={page === key ? "active" : ""}
              onClick={() => setPage(key)}
            >
              <Icon size={20} />
              <span className="nav-text">{label}</span>
              {page === key && <ChevronRight size={16} />}
            </button>
          ))}
        </nav>
      </aside>
      <main>
        <header className="topbar">
          <span>
            InspectMate <ChevronRight size={14} />{" "}
            {page === "inspect"
              ? "검사"
              : page === "experiments"
                ? "비교 실험"
                : "검사 이력"}
          </span>
          <div className="connection">
            <span className={status ? "dot" : "dot offline"} />
            {status ? "로컬 저장소 연결됨" : "서버 연결 확인 중"}
          </div>
        </header>
        <div className="workspace">
          <div className="page-heading">
            <div>
              <h1>
                {page === "inspect"
                  ? "금속 너트 외관 이상탐지"
                  : page === "experiments"
                    ? "비교 실험"
                    : "검사 이력"}
              </h1>
              <p>
                {page === "inspect"
                  ? METHOD_DESCRIPTIONS[method]
                  : page === "experiments"
                    ? "같은 이미지에서 검사 방식별 결과를 비교합니다."
                    : "검사 결과와 재검토 기록을 확인하세요."}
              </p>
            </div>
            <div className="heading-facts">
              <span className="catalog-number" aria-hidden="true">
                {page === "inspect"
                  ? "01"
                  : page === "experiments"
                    ? "02"
                    : "03"}
              </span>
              <span className="heading-fact-label">
                {page === "inspect"
                  ? "검사 도록"
                  : page === "experiments"
                    ? "검사 방식 비교"
                    : "검사 · 검토 기록"}
              </span>
              <span className={"mode-label " + (mode === "demo" ? "demo" : "")}>
                {mode === "demo"
                  ? "DEMO · 실제 분석 아님"
                  : "연구용 · 검사자 검토 필요"}
              </span>
            </div>
          </div>
          {error && (
            <div className="alert error" role="alert">
              <AlertTriangle size={18} />
              <span>{error}</span>
              <button aria-label="오류 닫기" onClick={() => setError("")}>
                ×
              </button>
            </div>
          )}
          {loadingResult && (
            <div className="notice" role="status">
              <span className="spinner" />
              최신 검사 기록을 불러오고 있습니다.
            </div>
          )}
          {status &&
            !status.data_ready &&
            (page === "experiments" ||
              (page === "inspect" &&
                mode !== "demo" &&
                (needsReference || needsDetector))) && (
              <div className="alert setup">
                <Settings2 size={20} />
                <div>
                  <strong>MVTec AD 데이터 설치가 필요합니다</strong>
                  <p>
                    {category}의 train/good와 test를 준비하고 manifest 생성
                    명령을 실행하세요. A 방식은 데이터셋 없이 업로드한 이미지로
                    사용할 수 있습니다.
                  </p>
                </div>
                <button onClick={loadStatus}>다시 확인</button>
              </div>
            )}
          {page === "inspect" && (
            <>
              <section className="control-panel">
                <div className="field">
                  <label htmlFor="category">검사 품목</label>
                  <select id="category" value={category} disabled>
                    <option>
                      {category}
                      {category === "metal_nut" ? " · 금속 너트" : ""}
                    </option>
                  </select>
                </div>
                <div className="field wide">
                  <label htmlFor="method">검사 방식</label>
                  <select
                    id="method"
                    value={method}
                    disabled={
                      busy || uploading || questionBusy || loadingResult
                    }
                    onChange={(e) => selectMethod(e.target.value)}
                  >
                    {Object.entries(METHODS).map(([k, v]) => (
                      <option key={k} value={k}>
                        {v}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="mode">실행 모드</label>
                  <select
                    id="mode"
                    value={mode}
                    disabled={
                      busy || uploading || questionBusy || loadingResult
                    }
                    onChange={(e) => {
                      initialMethodSet.current = true;
                      setMode(e.target.value);
                      if (e.target.value === "demo" && needsDetector)
                        setMethod("vlm_reference");
                      setAsset(null);
                      setResult(null);
                      setConsent(false);
                    }}
                  >
                    <option value="openai">실제 모델</option>
                    <option value="demo">데모 · 분석 없음</option>
                  </select>
                </div>
                <div className="run-actions">
                  {mode === "demo" ? (
                    <button
                      className="secondary"
                      onClick={demo}
                      disabled={busy || questionBusy || loadingResult}
                    >
                      데모 샘플 불러오기
                    </button>
                  ) : (
                    <button
                      className="secondary"
                      disabled={
                        busy || uploading || questionBusy || loadingResult
                      }
                      onClick={() => uploadRef.current?.click()}
                    >
                      <Upload size={17} />
                      {uploading ? "업로드 중…" : "이미지 업로드"}
                    </button>
                  )}
                  <input
                    ref={uploadRef}
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                    hidden
                    onChange={(e) => {
                      const files = Array.from(e.currentTarget.files ?? []);
                      e.currentTarget.value = "";
                      if (files.length) uploadFiles(files);
                    }}
                  />
                  <button
                    className="primary"
                    disabled={Boolean(runDisabledReason)}
                    title={runDisabledReason ?? "선택한 이미지 검사"}
                    aria-describedby="inspection-availability"
                    onClick={inspect}
                  >
                    {busy ? (
                      <span className="spinner" />
                    ) : (
                      <ScanLine size={18} />
                    )}
                    검사 실행
                  </button>
                </div>
              </section>
              {mode === "demo" ? (
                <div className="notice demo-notice">
                  데모 전용 도형 이미지와 명시적 데모 응답으로 화면·저장 흐름만
                  확인합니다. 실제 분석이나 MVTec 평가가 아닙니다.
                </div>
              ) : (
                method !== "patchcore" && (
                  <div className="consent-row">
                    <label>
                      <input
                        type="checkbox"
                        checked={consent}
                        disabled={uploading || loadingResult}
                        onChange={(e) => setConsent(e.target.checked)}
                      />{" "}
                      이 실행에서 {imageRoles(method)}를 OpenAI API로 전송하고
                      유료 호출하는 데 동의합니다.
                    </label>
                    <span>
                      {status?.external_api_enabled
                        ? status.api_key_configured
                          ? "서버 설정 완료"
                          : "API 키 설정 필요"
                        : "서버 외부 전송 허용 설정 필요"}
                    </span>
                  </div>
                )
              )}
              {busy && (
                <div className="notice">
                  <span className="spinner" /> 검사 중입니다. 완료된 결과는
                  이력에 저장됩니다.
                  <button onClick={() => abortRef.current?.abort()}>
                    화면 대기 취소
                  </button>
                </div>
              )}
              <div className="inspection-document">
                <aside className="document-index" aria-label="검사 기록 목차">
                  <span>이 기록의 구성</span>
                  <a href="#inspection-images">
                    <small>01</small>이미지 비교
                  </a>
                  <a href="#inspection-results">
                    <small>02</small>관찰 내용
                  </a>
                  {result && (
                    <a href="#inspection-review">
                      <small>03</small>검토 기록
                    </a>
                  )}
                </aside>
                <div className="document-content">
                  <div
                    id="inspection-images"
                    className={
                      "comparison-grid" + (showReference ? "" : " single-panel")
                    }
                  >
                    <ImageViewer
                      title="검사 이미지"
                      subtitle={
                        uploading
                          ? "이미지 업로드 중…"
                          : (result?.sample_id ??
                            (asset ? "이미지 업로드 완료" : "업로드 대기"))
                      }
                      src={asset?.url}
                      record={result ?? undefined}
                      onFilesDrop={uploadFiles}
                      uploading={uploading}
                      dropDisabled={
                        mode === "demo" || busy || uploading || questionBusy
                      }
                      uploadHint={
                        mode === "demo"
                          ? "제품 사진을 올리려면 ‘실제 모델’ 모드를 선택하세요."
                          : uploading
                            ? "이미지를 업로드하고 있습니다."
                            : busy || questionBusy
                              ? "진행 중인 작업이 끝난 뒤 이미지를 바꿀 수 있습니다."
                              : undefined
                      }
                      action={
                        <div className="inspection-action">
                          <div className="inspection-action-heading">
                            <strong>{METHODS[method]}</strong>
                            {mode === "openai" && method === "patchcore" && (
                              <span>로컬 검사 · API 호출 없음</span>
                            )}
                          </div>
                          <button
                            className="primary inspection-run-button"
                            disabled={Boolean(runDisabledReason)}
                            onClick={inspect}
                            aria-describedby="inspection-availability"
                          >
                            {busy ? (
                              <span className="spinner" />
                            ) : (
                              <ScanLine size={19} />
                            )}
                            {busy ? "검사 중…" : "검사 실행"}
                          </button>
                          <p
                            id="inspection-availability"
                            role="status"
                            aria-live="polite"
                          >
                            {runDisabledReason ??
                              "이미지가 준비됐습니다. 검사 실행을 눌러주세요."}
                          </p>
                          {canSwitchToLocal && (
                            <button
                              className="secondary"
                              onClick={() => selectMethod("patchcore")}
                            >
                              바로 사용 가능한 C · PatchCore로 바꾸기
                            </button>
                          )}
                        </div>
                      }
                    />
                    {showReference && (
                      <ImageViewer
                        title="정상 참조"
                        subtitle={
                          selectedRefs[0]?.image_id ?? "fit_normal에서만 선택"
                        }
                        src={selectedRefs[0]?.url}
                        reference
                      />
                    )}
                  </div>
                  <section className="result-panel" id="inspection-results">
                    <div className="section-header">
                      <h2>
                        <Layers size={20} /> 검사 결과
                      </h2>
                      {result && (
                        <button
                          className="text-button"
                          onClick={() =>
                            downloadJSON(
                              result,
                              `inspection-${result.inspection_id}.json`,
                            )
                          }
                        >
                          <Download size={16} />
                          원시 결과
                        </button>
                      )}
                    </div>
                    {!result ? (
                      <div className="result-empty">
                        <CircleHelp size={22} />
                        <span>
                          검사를 실행하면 판정과 관찰 근거가 이곳에 표시됩니다.
                        </span>
                        <Badge decision={null} />
                      </div>
                    ) : (
                      <>
                        <ReviewDisposition record={result} />
                        <div className="result-summary">
                          <div className="model-verdict">
                            <span>모델 원시 판정</span>
                            <Badge
                              decision={
                                result.execution_status === "failed"
                                  ? "failed"
                                  : result.final_decision
                              }
                            />
                          </div>
                          <div>
                            <p>
                              {result.method === "patchcore" &&
                              result.execution_status === "succeeded"
                                ? (detectorSummary(result) ??
                                  result.result?.summary)
                                : (result.result?.summary ??
                                  result.error_message)}
                            </p>
                            {detectorNeedsReview(result) && (
                              <span className="result-review-hint">
                                <AlertTriangle size={16} />
                                의심 영역 있음 · 재검토 필요
                              </span>
                            )}
                          </div>
                        </div>
                        {result.method === "patchcore_vlm" && (
                          <div className="decision-split">
                            <span>
                              탐지 모델{" "}
                              <Badge decision={result.detector_decision} />
                            </span>
                            <span>
                              VLM 원시 판정{" "}
                              <Badge decision={result.vlm_decision} />
                            </span>
                            <small>
                              두 모델이 다르게 판단하면 결합 결과는 판단
                              보류입니다.
                            </small>
                          </div>
                        )}
                        {result.result && result.method !== "patchcore" && (
                          <div className="result-columns">
                            <div>
                              <h3>관찰 근거</h3>
                              {result.result?.observations?.length ? (
                                result.result.observations.map(
                                  (o: Data, i: number) => (
                                    <div className="observation" key={i}>
                                      <span>
                                        {String(i + 1).padStart(2, "0")}
                                      </span>
                                      <div>
                                        <strong>{o.location}</strong>
                                        <p>{o.fact}</p>
                                        <small>
                                          {o.image_id}
                                          {o.reference_id
                                            ? " ↔ " + o.reference_id
                                            : ""}
                                        </small>
                                      </div>
                                    </div>
                                  ),
                                )
                              ) : (
                                <p className="subtle">
                                  기록된 관찰이 없습니다.
                                </p>
                              )}
                            </div>
                            <div>
                              <h3>불확실성 및 추가 확인</h3>
                              <ul>
                                {result.result?.uncertainties?.map(
                                  (u: string) => (
                                    <li key={u}>{u}</li>
                                  ),
                                )}
                              </ul>
                              <p>{result.result?.recommended_action}</p>
                              <span className="subtle">
                                설명 정확성:{" "}
                                {result.human_review_status === "unreviewed"
                                  ? "미평가"
                                  : "수동 검토 기록 있음"}
                              </span>
                            </div>
                          </div>
                        )}
                        <PatchCoreDiagnosis record={result} />
                        <div className="metrics-strip">
                          <Metric
                            label="실제 추론 시간"
                            value={
                              result.latency_ms != null
                                ? (result.latency_ms / 1000).toFixed(2) + "초"
                                : result.cache_hit
                                  ? "캐시 조회"
                                  : null
                            }
                          />
                          {resultUsesVlm && (
                            <>
                              <Metric
                                label="API 토큰"
                                value={result.usage?.total_tokens}
                              />
                              <Metric
                                label="비용"
                                value={
                                  result.cost_usd == null
                                    ? "미산정"
                                    : "$" + result.cost_usd.toFixed(5)
                                }
                              />
                            </>
                          )}
                          {usesDetector(result.method) &&
                            result.anomaly_score != null && (
                              <>
                                <Metric
                                  label="이상 점수 · 확률 아님"
                                  value={result.anomaly_score.toFixed(4)}
                                />
                                <Metric
                                  label="보정 임계값"
                                  value={result.threshold?.toFixed(4)}
                                />
                              </>
                            )}
                        </div>
                        <details className="metadata">
                          <summary>실행 기록 · 모델과 설정</summary>
                          <pre>
                            {JSON.stringify(
                              {
                                model: result.model,
                                provider: result.provider,
                                ...(resultUsesVlm
                                  ? {
                                      prompt_version: result.prompt_version,
                                      retry_count: result.retry_count,
                                      cache_hit: result.cache_hit,
                                    }
                                  : {}),
                                ...(usesReference(result.method) &&
                                !result.is_demo
                                  ? { reference_ids: result.reference_ids }
                                  : {}),
                                config_hash: result.config_hash,
                                is_demo: result.is_demo,
                                error_code: result.error_code,
                              },
                              null,
                              2,
                            )}
                          </pre>
                        </details>
                      </>
                    )}
                  </section>
                  {result && (
                    <div
                      id="inspection-review"
                      className={
                        "bottom-grid" + (showFollowup ? "" : " single-panel")
                      }
                    >
                      {showFollowup && (
                        <section className="panel">
                          <h2>추가 관찰</h2>
                          <p className="subtle">
                            이미지를 다시 살펴보고 관찰 내용을 확인합니다. 새
                            답변은 최초 모델 판정과 별도로 기록됩니다.
                          </p>
                          <div className="question-chips">
                            {[
                              ...(usesReference(result.method)
                                ? ["정상 제품과 다른 부분을 설명해줘."]
                                : [
                                    "이 이미지에서 이상으로 판단한 근거를 설명해줘.",
                                  ]),
                              "흠집과 빛 반사를 구분할 근거가 있어?",
                              "추가 촬영이 필요한 부분은 어디야?",
                            ].map((q) => (
                              <button key={q} onClick={() => setQuestion(q)}>
                                {q}
                              </button>
                            ))}
                          </div>
                          <textarea
                            aria-label="후속 질문"
                            value={question}
                            onChange={(e) => setQuestion(e.target.value)}
                            placeholder="이미지에서 확인할 수 있는 내용을 질문하세요."
                          />
                          <button
                            className="secondary"
                            disabled={
                              questionBusy ||
                              uploading ||
                              busy ||
                              !consent ||
                              result.is_demo ||
                              result.execution_status !== "succeeded" ||
                              result.method === "patchcore"
                            }
                            onClick={ask}
                          >
                            {questionBusy ? "응답 중…" : "질문하기"}
                            <ArrowRight size={16} />
                          </button>
                          {answer && (
                            <div className="answer">
                              <span className="answer-label">
                                재관찰 답변 · 모델 원시 판정과 별도
                              </span>
                              <p>{answer.answer}</p>
                              {answer.uncertainties?.map((x: string) => (
                                <small key={x}>{x}</small>
                              ))}
                            </div>
                          )}
                        </section>
                      )}
                      <section className="panel">
                        <h2>검사자 재검토</h2>
                        <select
                          aria-label="재검토 상태"
                          value={reviewStatus}
                          onChange={(e) => setReviewStatus(e.target.value)}
                        >
                          <option value="reviewed">검토 완료</option>
                          <option value="needs_followup">추가 확인 필요</option>
                          <option value="unreviewed">미검토</option>
                        </select>
                        {resultUsesVlm &&
                          result.execution_status === "succeeded" &&
                          Object.entries({
                            observation_exists: "관찰한 이상이 실제로 존재함",
                            location_matches: "위치 설명이 일치함",
                            unsupported_cause: "근거 없는 제조 원인을 단정함",
                            uncertainty_appropriate: "불확실성을 적절히 설명함",
                          }).map(([k, label]) => (
                            <label className="review-check" key={k}>
                              {label}
                              <select
                                value={
                                  reviewChecks[k] == null
                                    ? ""
                                    : String(reviewChecks[k])
                                }
                                onChange={(e) =>
                                  setReviewChecks({
                                    ...reviewChecks,
                                    [k]:
                                      e.target.value === ""
                                        ? null
                                        : e.target.value === "true",
                                  })
                                }
                              >
                                <option value="">미평가</option>
                                <option value="true">예</option>
                                <option value="false">아니오</option>
                              </select>
                            </label>
                          ))}
                        <textarea
                          aria-label="검사자 메모"
                          value={note}
                          onChange={(e) => setNote(e.target.value)}
                          placeholder={
                            result.method === "patchcore"
                              ? "판정과 의심 영역을 검토한 내용을 기록하세요."
                              : "관찰 설명의 정확성과 보완할 점을 기록하세요."
                          }
                        />
                        <button
                          className="secondary"
                          onClick={async () => {
                            try {
                              setResult(
                                await api(
                                  `/inspections/${result.inspection_id}/review`,
                                  {
                                    ...post({
                                      status: reviewStatus,
                                      note,
                                      ...Object.fromEntries(
                                        [
                                          "observation_exists",
                                          "location_matches",
                                          "unsupported_cause",
                                          "uncertainty_appropriate",
                                        ].map((k) => [
                                          k,
                                          showFollowup
                                            ? (reviewChecks[k] ?? null)
                                            : null,
                                        ]),
                                      ),
                                    }),
                                    method: "PATCH",
                                  },
                                ),
                              );
                            } catch (e) {
                              setError(String(e));
                            }
                          }}
                        >
                          검토 기록 저장
                        </button>
                      </section>
                    </div>
                  )}
                </div>
              </div>
            </>
          )}
          {page === "experiments" && (
            <>
              <section className="panel experiment-config">
                <h2>실험 설정</h2>
                <p className="subtle">
                  {experimentUsesVlm
                    ? (status?.model ?? "모델 확인 중")
                    : "PatchCore 로컬 검사"}
                  {experimentUsesReference && " · 정상 참조 1장 고정"}
                  {experimentUsesVlm && " · 캐시 사용 안 함"}
                </p>
                <div className="method-options">
                  {Object.entries(METHODS).map(([k, v]) => (
                    <label key={k}>
                      <input
                        type="checkbox"
                        checked={expMethods.includes(k)}
                        onChange={(e) =>
                          setExpMethods(
                            e.target.checked
                              ? [...expMethods, k]
                              : expMethods.filter((m) => m !== k),
                          )
                        }
                      />
                      {v}
                    </label>
                  ))}
                </div>
                <div className="experiment-options">
                  <label>
                    미리보기 샘플 수{" "}
                    <input
                      type="number"
                      min="1"
                      max="10"
                      disabled={full}
                      value={sampleLimit}
                      onChange={(e) => setSampleLimit(Number(e.target.value))}
                    />
                  </label>
                  <label>
                    <input
                      type="checkbox"
                      checked={full}
                      onChange={(e) => setFull(e.target.checked)}
                    />{" "}
                    전체 test 평가를 명시적으로 선택
                  </label>
                  <label>
                    <input
                      type="checkbox"
                      checked={exploratory}
                      onChange={(e) => setExploratory(e.target.checked)}
                    />{" "}
                    탐색 실험 (exploratory)
                  </label>
                </div>
                <p className="subtle">
                  최종 평가로 기록하려면 프롬프트·참조·임계값을 동결하고, test를
                  보고 설정을 수정하지 않았는지 확인하세요.
                </p>
                {experimentUsesVlm && (
                  <div className="consent-row">
                    <label>
                      <input
                        type="checkbox"
                        checked={expConsent}
                        onChange={(e) => setExpConsent(e.target.checked)}
                      />{" "}
                      이 배치의{" "}
                      {expMethods.includes("patchcore_vlm")
                        ? imageRoles("patchcore_vlm")
                        : experimentUsesReference
                          ? imageRoles("vlm_reference")
                          : imageRoles("vlm_only")}
                      를 OpenAI API에 전송하고 유료 호출하는 데 동의합니다.
                    </label>
                  </div>
                )}
                <div className="button-row">
                  <button
                    className="secondary"
                    disabled={!status?.data_ready || !expMethods.length}
                    onClick={async () => {
                      try {
                        setPreview(
                          await api(
                            "/experiments/preview",
                            post(experimentRequest),
                          ),
                        );
                      } catch (e) {
                        setError(String(e));
                      }
                    }}
                  >
                    {experimentUsesVlm
                      ? "호출 수 미리보기"
                      : "실험 구성 미리보기"}
                  </button>
                  <button
                    className="primary"
                    disabled={
                      !preview ||
                      experiment?.status === "running" ||
                      (preview.planned_api_calls > 0 && !expConsent)
                    }
                    onClick={async () => {
                      try {
                        setExperiment(
                          await api("/experiments", post(experimentRequest)),
                        );
                      } catch (e) {
                        setError(String(e));
                      }
                    }}
                  >
                    <Play size={16} />
                    실험 실행
                  </button>
                </div>
                {preview && (
                  <div className="metrics-strip">
                    <Metric label="샘플 수" value={preview.sample_count} />
                    {experimentUsesVlm && (
                      <>
                        <Metric
                          label="예정 API 호출"
                          value={preview.planned_api_calls}
                        />
                        <Metric
                          label="재시도 포함 최대 시도"
                          value={preview.maximum_attempts}
                        />
                        <Metric
                          label="외부 요청 한도"
                          value={preview.request_limit}
                        />
                        <Metric label="비용" value="미산정" />
                      </>
                    )}
                  </div>
                )}
              </section>
              {experiment && (
                <section className="panel">
                  <div className="section-header">
                    <h2>
                      {experiment.status === "running"
                        ? "비교 실험 진행 중"
                        : experiment.status === "cancelled"
                          ? "실험 취소됨"
                          : experiment.status === "failed"
                            ? "실험 실패"
                            : "비교 실험 결과"}
                    </h2>
                    {experiment.status === "running" && (
                      <button
                        className="secondary"
                        onClick={() =>
                          api(
                            "/experiments/" +
                              experiment.experiment_id +
                              "/cancel",
                            post(),
                          ).then(setExperiment)
                        }
                      >
                        <Square size={14} />
                        남은 검사 취소
                      </button>
                    )}
                  </div>
                  <progress
                    max={experiment.total}
                    value={experiment.completed}
                  />
                  <p className="subtle">
                    실제 처리 {experiment.completed} / {experiment.total} ·{" "}
                    {experiment.preview.exploratory
                      ? "탐색 실험"
                      : "최종 설정 평가"}
                  </p>
                  {experiment.error && (
                    <div className="alert error">{experiment.error}</div>
                  )}
                  {experiment.metrics && (
                    <>
                      <div className="table-wrap">
                        <table>
                          <thead>
                            <tr>
                              <th>방식</th>
                              <th>성공 / 실패 / 보류</th>
                              <th>자동 판정</th>
                              <th>불량 통과</th>
                              <th>정상 오탐</th>
                              <th>선택 F1 (표본)</th>
                              <th>추론 p95</th>
                            </tr>
                          </thead>
                          <tbody>
                            {Object.entries(experiment.metrics.methods).map(
                              ([m, x]) => {
                                const v = x as Data;
                                return (
                                  <tr key={m}>
                                    <td>{METHODS[m]}</td>
                                    <td>
                                      {v.succeeded} / {v.failed} / {v.uncertain}
                                    </td>
                                    <td>{rate(v.automatic_coverage)}</td>
                                    <td>{rate(v.defect_pass_rate)}</td>
                                    <td>{rate(v.normal_false_alarm_rate)}</td>
                                    <td>
                                      {rate(v.selective.f1)} (
                                      {v.selective.subset_size})
                                    </td>
                                    <td>
                                      {v.latency.p95_ms == null
                                        ? "N/A"
                                        : (v.latency.p95_ms / 1000).toFixed(2) +
                                          "초"}
                                    </td>
                                  </tr>
                                );
                              },
                            )}
                          </tbody>
                        </table>
                      </div>
                      <p className="notice">
                        낮은 불량 통과율은 자동 판정 커버리지·보류·실패율과 함께
                        해석하세요. 선택 F1은 명확히 판정한 표본에서만
                        계산합니다.
                      </p>
                      <div className="download-row">
                        {[
                          "predictions.jsonl",
                          "metrics.json",
                          "comparison.csv",
                          "report.md",
                          "run_config.json",
                        ].map((n) => (
                          <a
                            className="text-button"
                            key={n}
                            href={`/api/experiments/${experiment.experiment_id}/download/${n}`}
                            download
                          >
                            <Download size={15} />
                            {n}
                          </a>
                        ))}
                      </div>
                      <details>
                        <summary>
                          2×4 교차표
                          {experiment.metrics.methods.patchcore_vlm &&
                            " · D 원시 판정"}{" "}
                          · 전체 지표
                        </summary>
                        <pre>{JSON.stringify(experiment.metrics, null, 2)}</pre>
                      </details>
                    </>
                  )}
                </section>
              )}
              {cases.length > 0 && (
                <section className="panel">
                  <div className="section-header">
                    <h2>평가 사례 검토</h2>
                    <select
                      aria-label="평가 사례 필터"
                      value={caseFilter}
                      onChange={(e) => setCaseFilter(e.target.value)}
                    >
                      <option value="all">모든 사례</option>
                      <option value="false_negative">불량 통과</option>
                      <option value="false_positive">정상 오탐</option>
                      <option value="uncertain">판단 보류</option>
                      <option value="failed">실행 실패</option>
                    </select>
                  </div>
                  <div className="case-grid">
                    {filteredCases.slice(0, 40).map((r) => (
                      <div className="case" key={r.sample_id + r.method}>
                        <strong>
                          {r.sample_id} · {METHODS[r.method]}
                        </strong>
                        {r.image_url && (
                          <img src={r.image_url} alt="평가 검사 이미지" />
                        )}
                        <span>
                          정답: {r.truth === "normal" ? "정상" : "불량"} / 예측:{" "}
                          {DECISIONS[r.final_decision] ?? "실패"}
                        </span>
                        {r.mask_available && (
                          <details>
                            <summary>평가용 정답 마스크 보기</summary>
                            <img
                              src={`/api/experiments/${experiment?.experiment_id}/masks/${r.sample_id}`}
                              alt="평가 전용 정답 마스크, 추론에 미사용"
                            />
                          </details>
                        )}
                        <button
                          className="text-button"
                          disabled={!r.inspection_id}
                          onClick={() => openResult(r)}
                        >
                          검사 상세
                        </button>
                      </div>
                    ))}
                  </div>
                  <small>
                    화면에는 최대 40개, 전체 사례는 comparison.csv에서
                    확인하세요.
                  </small>
                </section>
              )}
              <section className="panel">
                <h2>저장된 실험</h2>
                {!experiments.length ? (
                  <p className="subtle">
                    실험 기록이 없습니다. 성능은 미측정입니다.
                  </p>
                ) : (
                  experiments.map((e) => (
                    <button
                      className="experiment-row"
                      key={e.experiment_id}
                      onClick={() => setExperiment(e)}
                    >
                      <span>
                        {new Date(e.created_at).toLocaleString("ko-KR")}
                      </span>
                      <span>
                        {e.preview.sample_count}개 · {e.status}
                      </span>
                      <ChevronRight size={16} />
                    </button>
                  ))
                )}
              </section>
            </>
          )}
          {page === "history" && (
            <section className="panel">
              <div className="history-filters">
                <input
                  aria-label="품목 필터"
                  placeholder="품목 전체"
                  value={filter.category}
                  onChange={(e) =>
                    setFilter({ ...filter, category: e.target.value })
                  }
                />
                <select
                  aria-label="방식 필터"
                  value={filter.method}
                  onChange={(e) =>
                    setFilter({ ...filter, method: e.target.value })
                  }
                >
                  <option value="">모든 검사 방식</option>
                  {Object.entries(METHODS).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
                <select
                  aria-label="모델 원시 판정 필터"
                  value={filter.decision}
                  onChange={(e) =>
                    setFilter({ ...filter, decision: e.target.value })
                  }
                >
                  <option value="">모든 모델 판정</option>
                  {Object.entries(DECISIONS)
                    .filter(([k]) => k !== "failed")
                    .map(([k, v]) => (
                      <option key={k} value={k}>
                        {v}
                      </option>
                    ))}
                </select>
                <select
                  aria-label="실행 상태 필터"
                  value={filter.status}
                  onChange={(e) =>
                    setFilter({ ...filter, status: e.target.value })
                  }
                >
                  <option value="">모든 실행 상태</option>
                  <option value="succeeded">성공</option>
                  <option value="failed">실패</option>
                </select>
                <input
                  aria-label="검사 날짜"
                  type="date"
                  value={filter.date}
                  onChange={(e) =>
                    setFilter({ ...filter, date: e.target.value })
                  }
                />
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>검사 시각</th>
                      <th>품목 / 모드</th>
                      <th>검사 방식</th>
                      <th>검토 상태</th>
                      <th>모델 원시 판정</th>
                      <th>실행 상태</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history
                      .filter(
                        (r) =>
                          !filter.date ||
                          new Date(r.created_at).toLocaleDateString("sv-SE") ===
                            filter.date,
                      )
                      .map((r) => (
                        <tr key={r.inspection_id}>
                          <td>
                            <button
                              className="text-button"
                              onClick={() => openResult(r)}
                            >
                              {new Date(r.created_at).toLocaleString("ko-KR")}
                            </button>
                          </td>
                          <td>
                            {r.category}
                            <small className="block">
                              {r.is_demo ? "DEMO · 분석 없음" : "실제 모드"}
                            </small>
                          </td>
                          <td>{METHODS[r.method]}</td>
                          <td>
                            <ReviewStatus record={r} />
                          </td>
                          <td>
                            <Badge
                              decision={
                                r.execution_status === "failed"
                                  ? "failed"
                                  : r.final_decision
                              }
                            />
                          </td>
                          <td>
                            {r.execution_status === "succeeded"
                              ? "완료"
                              : r.execution_status === "failed"
                                ? "실패"
                                : "진행 중"}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
              {!history.length && (
                <div className="history-empty">
                  <History size={32} />
                  <h3>검사 기록이 없습니다</h3>
                  <p>이미지를 검사하면 결과가 로컬 저장소에 기록됩니다.</p>
                  <button
                    className="secondary"
                    onClick={() => setPage("inspect")}
                  >
                    검사로 이동
                  </button>
                </div>
              )}
            </section>
          )}
          <footer>
            <span>InspectMate / 연구용 프로토타입</span>
            <span>
              실행하지 않은 성능: 미측정 · 설명 정확성: 수동 검토 필요
            </span>
          </footer>
        </div>
      </main>
    </div>
  );
}
