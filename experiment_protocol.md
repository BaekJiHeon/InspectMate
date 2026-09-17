# Experiment protocol v1

## 2026-09-17 탐색 변경 기록

알려진 scratch 테스트 사례와 사용자 피드백을 확인한 후 초기 VLM 기준을 `appearance-v2-observation-first`, 프롬프트를 `inspection-v2-observation-first`로 보완했습니다. 같은 사례의 새 B 결과는 불량 의심이지만, 이 재확인은 독립 평가가 아닙니다. 구버전 기록을 보존하며 v1/v2 결과를 같은 동결 설정의 정식 비교로 합치지 않습니다. 새 기준의 정식 성능 주장은 조정에 사용하지 않은 별도 평가가 필요합니다. 사용자 검토 상태는 모델 원시 판정·평가 지표와 분리합니다.

## 연구 질문

1. A 대비 정상 참조 1장을 추가한 B가 이상 판정을 개선하는가?
2. B 대비 PatchCore 검토 후보 crop을 추가한 D의 **VLM 원시 판정**이 개선되는가?
3. D 결합 정책은 자동 판정 coverage와 불량 통과율을 어떻게 바꾸는가?

성능 향상은 가설입니다. D가 개선되어도 곧바로 VLM의 공이라고 해석하지 않고 C·D 원시 VLM·D 최종 결합을 나눠 봅니다.

## 분리·동결

고유 RGB pixel hash를 정렬하고 seed=42로 shuffle하여 fit 80% / calibration 20%. 각 그룹의 중복 파일은 같은 split. test와 hash가 겹치면 중단. 이미지 ID는 content hash 기반 중립 ID이며 test 구성에 의존하지 않습니다. 정상 참조는 fit 고유 해시에서 seed=42로 고정 1장. 모든 query에서 같은 참조 사용.

calibration은 메모리/참조에 사용하지 않습니다. 정답·결함 폴더명·마스크·원본 경로·정답 설명은 `VLMInput`에 필드가 없습니다. A/B는 query 바이트, 모델, 공통 system prompt, 기준, 전처리, JSON schema, generation 설정이 동일하며 reference role+image만 추가됩니다.

개발 중 test 결과를 보고 변경했다면 exploratory. 최종 실행은 별도 동결된 설정과 사용자 `--final` 선언으로 기록하지만 데이터 열람 이력을 자동 보증하지 않습니다. 외부 VLM 사전학습에 공개 benchmark가 포함되었는지는 unknown.

## PatchCore

anomalib 2.3.1 raw Torch 모델을 사용합니다. fit forward로 embedding_store를 채우고 `subsample_embedding(sampling_ratio=.1)` 후 eval. test를 쓰는 Engine/자동 validation/후처리 설정은 없습니다.

전처리: RGB → 256×256 letterbox(bilinear, black padding) → ImageNet normalization. 정확한 원본 크기·정수 resize·padding을 저장하고 map을 padding 제거 후 원본 좌표로 복원합니다.

정상 calibration 이미지 점수 95백분위수, 픽셀 지도 99.5백분위수, method=linear. 지도 픽셀은 이미지당 최대 100,000개를 일정 stride로 추출. heatmap 색상 범위는 정상 calibration 1~99.9백분위수로 고정. query마다 최대값을 빨갛게 정규화하지 않습니다.

ROI는 원본 좌표 map의 임계값 초과 연결 영역에서 생성. 최소 면적 max(9, 원본면적×0.0005), padding=max(1, 짧은변×0.02), 겹친 padded 박스 병합, peak score 내림차순 최대 3개. 없으면 빈 목록. 실제 원본 crop과 전체 query를 D에 전달하고 검토 후보라고 명시. detector normal이어도 VLM을 호출합니다.

결합: N/N→N, D/D→D, 불일치 또는 VLM U→U. 필수 단계 실패는 execution failed, final_decision=null. 재사용한 map은 PatchCore 결과이지 VLM의 픽셀 예측이 아닙니다.

## 평가 수식

정답 2종(normal, defect) × 예측 4종(normal, defect_suspected, uncertain, failed) 교차표. N은 모든 예정 샘플이며 누락/중복/다른 ID 집합은 evaluator 오류입니다.

- coverage = (TN+TP+FN+FP)/N.
- 실제 불량 통과율 = FN / 전체 실제 불량 수 (보류·실패 포함).
- 실제 정상 오탐률 = FP / 전체 실제 정상 수 (보류·실패 포함).
- 클래스별 보류/실패율도 그 클래스 전체 수가 분모.
- 명확 판정 subset precision = TP/(TP+FP), recall = TP/(TP+FN), F1=2TP/(2TP+FP+FN). subset 크기와 클래스별 수도 기록.
- 분모 0은 null + reason → N/A. 모두 보류면 coverage=0, selective 지표 N/A. `recall=1−불량통과율`로 계산하지 않음.
- image AUROC는 실제 detector 연속 score에만 계산하고 scored coverage·N을 함께 기록.
- 실제 map이 있고 mask가 제공되는 경우 PatchCore pixel IoU/precision/recall을 고정 pixel threshold에서 계산. 정상 정답은 영 mask. 불량 mask가 없으면 누락 mask 수 표시.

latency 중앙값/p95(method=linear)는 non-cache 실제 시도만. 호출 전 차단은 null. 실패 latency를 삭제하지 않고 성공/실패별도 제공. D는 detector·VLM 측정값도 별도 저장. cache hit의 lookup을 추론 시간과 섞지 않음. reported usage와 unknown 사용량 레코드 수를 분리하고 누락 usage를 0으로 만들지 않음.

## 설명 평가

별도 검사자 검토: 관찰 실재, 위치 일치, 근거 없는 원인 단정 여부, 불확실성 표현. UI에서 각각 예/아니오/미평가와 메모를 저장. 검토 전 정확도는 미평가. 마스크·JSON 검증만으로 자연어 설명을 검증했다고 주장하지 않음.

추론 저장 후 별도 evaluator가 정답을 읽습니다. 후속 질문과 수동 검토는 최초 predictions 파일/판정을 덮어쓰지 않습니다.
