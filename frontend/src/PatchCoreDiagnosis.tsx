import { AlertTriangle, CircleHelp } from "lucide-react";

type ROI = { box: number[]; peak_score?: number };
type DetectorRecord = {
  method?: string;
  is_demo?: boolean;
  inspection_id?: string;
  image_url?: string;
  image_width?: number;
  image_height?: number;
  heatmap_file?: string;
  anomaly_score?: number;
  threshold?: number;
  pixel_threshold?: number;
  detector_decision?: string;
  roi?: ROI[];
  detector_metadata?: {
    calibration_scores?: number[];
    fit_ids?: string[];
    calibration_count?: number;
    memory_shape?: number[];
    config?: { backbone?: string; size?: number; image_quantile?: number };
  };
};

const finite = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);
const number = (value: unknown) =>
  finite(value) ? value.toFixed(3) : "기록 없음";

export function detectorNeedsReview(record: DetectorRecord) {
  return (
    !record.is_demo &&
    ["patchcore", "patchcore_vlm"].includes(record.method ?? "") &&
    record.detector_decision === "normal" &&
    (record.roi?.length ?? 0) > 0
  );
}

export function detectorSummary(record: DetectorRecord) {
  if (!finite(record.anomaly_score) || !finite(record.threshold)) return null;
  if (detectorNeedsReview(record))
    return "이미지 점수는 불량 판정 기준을 넘지 않았지만, 국소 의심 영역이 있습니다. 해당 부위를 재검토하세요.";
  return record.detector_decision === "defect_suspected"
    ? "이미지 점수가 정상 데이터로 정한 기준을 넘어 불량이 의심됩니다. 원본과 의심 영역을 확인하세요."
    : "이미지 점수가 불량 판정 기준을 넘지 않았고, 검토 후보 영역이 검출되지 않았습니다.";
}

function ScoreDistribution({ record }: { record: DetectorRecord }) {
  const score = record.anomaly_score!;
  const threshold = record.threshold!;
  const scores = (record.detector_metadata?.calibration_scores ?? []).filter(
    finite,
  );
  const values = [...scores, score, threshold];
  const lo = Math.min(...values),
    hi = Math.max(...values);
  const span = Math.max(hi - lo, 1);
  const start = lo - span * 0.1,
    end = hi + span * 0.1;
  const x = (value: number) => 40 + ((value - start) / (end - start)) * 800;
  const ticks = Array.from(
    { length: 6 },
    (_, i) => start + ((end - start) * i) / 5,
  );
  const above = scores.filter((value) => value > score).length;
  return (
    <div className="score-distribution">
      <div className="diagnosis-chart-heading">
        <div>
          <h3>정상 사진들의 점수와 비교</h3>
          <p>회색 점은 기준 설정에 사용한 정상 사진입니다.</p>
        </div>
        <div className="score-comparison">
          <strong>{number(score)}</strong>
          <span>{score > threshold ? ">" : "≤"}</span>
          <strong>{number(threshold)}</strong>
          <small>검사 점수 / 이미지 판정 기준</small>
        </div>
      </div>
      <div
        className="score-chart-scroll"
        tabIndex={0}
        aria-label="점수 분포 그래프, 좁은 화면에서는 가로로 이동할 수 있습니다"
      >
        <svg
          viewBox="0 0 880 190"
          className="score-chart"
          role="img"
          aria-label={`이미지 점수 ${number(score)}, 불량 판정 기준 ${number(threshold)}. 정상 기준 설정 사진 ${scores.length}장 중 이번 사진보다 점수가 높은 사진 ${above}장.`}
        >
          {ticks.map((tick) => (
            <g key={tick}>
              <line
                x1={x(tick)}
                x2={x(tick)}
                y1="18"
                y2="144"
                className="score-grid"
              />
              <text x={x(tick)} y="166" textAnchor="middle">
                {tick.toFixed(1)}
              </text>
            </g>
          ))}
          <line x1="40" x2="840" y1="144" y2="144" className="score-axis" />
          <line
            x1={x(threshold)}
            x2={x(threshold)}
            y1="16"
            y2="144"
            className="score-threshold"
          />
          {scores.map((value, i) => (
            <circle
              key={i}
              cx={x(value)}
              cy={110 + (i % 3) * 7}
              r="4.5"
              className="score-normal"
              tabIndex={0}
              aria-label={`정상 기준 사진 ${i + 1}, 점수 ${number(value)}`}
            >
              <title>{`정상 기준 사진 ${i + 1}: ${number(value)}`}</title>
            </circle>
          ))}
          <path
            d={`M ${x(score)} 47 l 9 9 l -9 9 l -9 -9 Z`}
            className="score-query"
          >
            <title>{`이번 검사 이미지: ${number(score)}`}</title>
          </path>
          <text
            x={x(score)}
            y="35"
            textAnchor="middle"
            className="score-query-label"
          >
            검사 {number(score)}
          </text>
          <text
            x={x(threshold) + (x(threshold) > 720 ? -12 : 12)}
            y="86"
            textAnchor={x(threshold) > 720 ? "end" : "start"}
            className="score-threshold-label"
          >
            기준 {number(threshold)}
          </text>
        </svg>
      </div>
      <div className="score-legend">
        <span>
          <i className="legend-normal" />
          정상 기준 사진 {scores.length}장
        </span>
        <span>
          <i className="legend-query" />
          이번 검사 이미지
        </span>
        <span>
          <i className="legend-threshold" />
          이미지 판정 기준
        </span>
      </div>
      <p className="diagnosis-footnote">
        {scores.length > 0
          ? `정상 기준 사진 ${scores.length}장 중 ${above}장은 이번 사진보다 점수가 높습니다.`
          : "이 검사에는 정상 점수 분포가 기록되어 있지 않습니다."}{" "}
        점수는 불량 확률이나 흠집의 크기가 아닙니다.
      </p>
    </div>
  );
}

export default function PatchCoreDiagnosis({
  record,
}: {
  record: DetectorRecord;
}) {
  if (
    record.is_demo ||
    !["patchcore", "patchcore_vlm"].includes(record.method ?? "") ||
    !finite(record.anomaly_score) ||
    !finite(record.threshold)
  )
    return null;
  const rois = record.roi ?? [];
  const review = detectorNeedsReview(record);
  const peaks = rois.map((roi) => roi.peak_score).filter(finite);
  const peak = peaks.length ? Math.max(...peaks) : null;
  const meta = record.detector_metadata;
  return (
    <section className="patchcore-diagnosis" aria-label="PatchCore 판정 근거">
      <div className="diagnosis-heading">
        <div>
          <span className="eyebrow">PATCHCORE EVIDENCE</span>
          <h2>어디를 보고, 왜 이렇게 판단했나요?</h2>
        </div>
        <span className="diagnosis-label">실제 검사 결과</span>
      </div>
      <div
        className={"diagnosis-message" + (review ? " needs-review" : "")}
        role="note"
      >
        {review ? <AlertTriangle size={22} /> : <CircleHelp size={22} />}
        <div>
          <strong>
            {review
              ? "의심 영역 재검토 필요"
              : record.detector_decision === "defect_suspected"
                ? "이미지 불량 판정 기준 초과"
                : "이미지 불량 판정 기준 미초과"}
          </strong>
          <p>{detectorSummary(record)}</p>
          {review && (
            <small>
              검토 안내입니다. 저장된 PatchCore 판정과 D 방식의 최종 판정은
              그대로 표시합니다.
            </small>
          )}
        </div>
      </div>
      <div className="diagnosis-images">
        {(["original", "heatmap", "roi"] as const).map((kind, index) => (
          <figure key={kind}>
            <h3>
              <span>{String(index + 1).padStart(2, "0")}</span>
              {kind === "original"
                ? "검사 원본"
                : kind === "heatmap"
                  ? "위치별 이상 지도"
                  : "의심 영역"}
            </h3>
            <div className="diagnosis-image-stage">
              {record.image_url && (
                <img
                  src={record.image_url}
                  alt={
                    kind === "original" ? "업로드한 검사 원본" : "검사 이미지"
                  }
                  loading="lazy"
                />
              )}
              {kind === "heatmap" &&
                (record.heatmap_file ? (
                  <img
                    className="diagnosis-map"
                    src={`/api/inspections/${record.inspection_id}/heatmap`}
                    alt="위치별 이상 점수, 노란색일수록 높은 점수"
                    loading="lazy"
                  />
                ) : (
                  <span className="diagnosis-image-missing">
                    이상 지도 기록 없음
                  </span>
                ))}
              {kind === "roi" &&
                rois.length > 0 &&
                finite(record.image_width) &&
                finite(record.image_height) && (
                  <svg
                    viewBox={`0 0 ${record.image_width} ${record.image_height}`}
                    role="img"
                    aria-label={`검토 후보 영역 ${rois.length}개`}
                  >
                    {rois.map((roi, i) => (
                      <rect
                        key={i}
                        x={roi.box[0]}
                        y={roi.box[1]}
                        width={roi.box[2] - roi.box[0]}
                        height={roi.box[3] - roi.box[1]}
                        fill="none"
                        stroke="#fbbf24"
                        strokeWidth="2.5"
                        vectorEffect="non-scaling-stroke"
                      >
                        <title>{`후보 ${i + 1}, 영역 최대 점수 ${number(roi.peak_score)}`}</title>
                      </rect>
                    ))}
                  </svg>
                )}
            </div>
            <figcaption>
              {kind === "original"
                ? "입력된 사진을 그대로 표시합니다."
                : kind === "heatmap"
                  ? "노란색일수록 정상 특징과 차이가 큽니다."
                  : rois.length
                    ? `주황 박스 ${rois.length}개 · 확정된 불량 영역이 아닌 검토 후보`
                    : "위치별 기준을 넘는 검토 후보가 없습니다."}
            </figcaption>
          </figure>
        ))}
      </div>
      <div className="diagnosis-criteria">
        <div>
          <h3>이미지 전체 판정</h3>
          <p>
            <strong>{number(record.anomaly_score)}</strong>
            <span>{record.anomaly_score > record.threshold ? ">" : "≤"}</span>
            <strong>{number(record.threshold)}</strong>
          </p>
          <small>검사 점수 / 이미지 판정 기준</small>
        </div>
        <div>
          <h3>국소 의심 영역</h3>
          <p>
            {peak !== null ? (
              <>
                <strong>{number(peak)}</strong>
                <span>
                  {finite(record.pixel_threshold)
                    ? peak > record.pixel_threshold
                      ? ">"
                      : "≤"
                    : "/"}
                </span>
                <strong>{number(record.pixel_threshold)}</strong>
              </>
            ) : (
              <strong>검토 후보 없음</strong>
            )}
          </p>
          <small>
            {peak !== null
              ? "후보 영역 최대 점수 / 위치별 표시 기준"
              : `위치별 표시 기준 ${number(record.pixel_threshold)}`}
          </small>
        </div>
      </div>
      <p className="diagnosis-footnote">
        이미지 판정과 영역 표시는 계산 방법과 기준이 다릅니다. 박스가 있어도
        이미지 판정은 정상일 수 있습니다. 데이터셋의 정답 영역은 실험 결과의
        평가 화면에서 확인할 수 있습니다.
      </p>
      <ScoreDistribution record={record} />
      <details className="diagnosis-how">
        <summary>PatchCore 검사 과정 보기</summary>
        <ol>
          <li>
            정상 사진 {meta?.fit_ids?.length ?? "—"}장에서{" "}
            {meta?.config?.backbone ?? "특징 추출기"}로 특징을 추출하고 대표
            특징 {meta?.memory_shape?.[0]?.toLocaleString() ?? "—"}개를
            저장합니다.
          </li>
          <li>
            검사 사진을 {meta?.config?.size ?? "—"}×{meta?.config?.size ?? "—"}
            로 변환하고, 각 위치의 특징을 저장된 정상 특징과 비교합니다.
          </li>
          <li>
            가장 의심스러운 위치의 거리와 주변 정상 특징을 이용해 이미지 점수를
            계산합니다. 위치별 점수의 단순 평균은 아닙니다.
          </li>
          <li>
            별도 정상 사진 {meta?.calibration_count ?? "—"}장의 점수로 정한 기준
            {finite(meta?.config?.image_quantile)
              ? ` (정상 점수의 ${meta.config.image_quantile * 100}백분위수)`
              : ""}
            과 비교합니다. 입력 이미지 업로드만으로 모델이 다시 학습되지는
            않습니다.
          </li>
        </ol>
      </details>
    </section>
  );
}
