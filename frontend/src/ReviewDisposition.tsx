type ReviewRecord = {
  execution_status?: string;
  is_demo?: boolean;
  final_decision?: string;
  human_review_status?: string;
  roi?: unknown[];
  human_review?: {
    observation_exists?: boolean | null;
    location_matches?: boolean | null;
    unsupported_cause?: boolean | null;
    uncertainty_appropriate?: boolean | null;
  };
};

export function reviewDisposition(record: ReviewRecord) {
  if (record.execution_status === "failed")
    return {
      code: "failed",
      label: "실행 실패",
      reason: "검사를 완료하지 못했습니다. 오류 내용을 확인하세요.",
    };
  if (record.is_demo)
    return {
      code: "demo",
      label: "데모 결과",
      reason: "실제 제품 분석 결과가 아닙니다.",
    };
  if (record.execution_status !== "succeeded")
    return {
      code: "pending",
      label: "검사 진행 중",
      reason: "검사가 완료되면 검토할 수 있습니다.",
    };
  const checks = record.human_review;
  const explanationFlagged =
    checks?.observation_exists === false ||
    checks?.location_matches === false ||
    checks?.unsupported_cause === true ||
    checks?.uncertainty_appropriate === false;
  if (record.human_review_status === "needs_followup" || explanationFlagged)
    return {
      code: "review",
      label: "추가 검토 필요",
      reason: explanationFlagged
        ? "관찰 설명의 정확성에 확인할 사항이 기록되어 있습니다."
        : "검사자가 추가 확인이 필요하다고 기록했습니다.",
    };
  if (record.human_review_status === "reviewed")
    return {
      code: "reviewed",
      label: "검토 기록 있음",
      reason:
        "검사자의 관찰 검토가 저장되었습니다. 제품 합격 여부를 뜻하지 않습니다.",
    };
  if (record.final_decision === "defect_suspected")
    return {
      code: "suspected",
      label: "불량 의심 · 검토 필요",
      reason: "모델이 외관 이상을 의심했습니다. 원본과 관찰 근거를 확인하세요.",
    };
  if ((record.roi?.length ?? 0) > 0)
    return {
      code: "review",
      label: "의심 영역 검토 필요",
      reason: `검토 후보 ${record.roi!.length}개가 있습니다. 원본과 모델별 관찰 근거를 함께 확인하세요.`,
    };
  if (record.final_decision === "uncertain")
    return {
      code: "review",
      label: "판단 보류 · 검토 필요",
      reason:
        "정보가 부족하거나 모델 판정이 일치하지 않습니다. 추가 관찰이 필요합니다.",
    };
  return {
    code: "review",
    label: "검토 대기",
    reason:
      "모델은 정상으로 분류했지만, 검사자가 확인하기 전에는 제품 합격으로 확정하지 않습니다.",
  };
}

export function ReviewStatus({ record }: { record: ReviewRecord }) {
  const state = reviewDisposition(record);
  return <span className={`review-status ${state.code}`}>{state.label}</span>;
}

export default function ReviewDisposition({
  record,
}: {
  record: ReviewRecord;
}) {
  const state = reviewDisposition(record);
  return (
    <section
      className={`review-disposition ${state.code}`}
      aria-label="검사 검토 상태"
    >
      <div className="disposition-label">검토 상태</div>
      <div>
        <h3>{state.label}</h3>
        <p>{state.reason}</p>
      </div>
      <span className="disposition-index">REVIEW</span>
    </section>
  );
}
