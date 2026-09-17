# Architecture

## 경계

```text
React UI (localhost:5173)
    ↓ /api proxy
FastAPI (localhost:8740)
    ├─ SQLite: 업로드 메타 / 검사 / 후속 질문 / 재검토 / 실험
    ├─ 로컬 RGB 이미지 / neutral manifest / 참조 / cache
    ├─ OpenAIProvider → Responses API (명시적 허용 + 요청 동의)
    ├─ DemoProvider → 전용 UI fixture만, 실제 분석 없음
    └─ 선택적 raw Torch PatchCore → 메모리 / calibration / ROI

inference_manifest → 중립 ID·이미지만 추론 → predictions.jsonl 닫기
                                                   ↓
evaluator_truth + private_masks ──────────────→ offline evaluator
                                                   ↓
                                  metrics / comparison.csv / report
```

## 파일별 책임

- `dataset.py`: hash-group split, 고정 참조, 원본 provenance와 추론용 DTO 분리.
- `images.py`: 디코딩/크기 검증, RGB 정규화, 비율 유지 resize/padding과 좌표 복원.
- `providers.py`: 교체 가능한 provider, 공통 A/B 입력, strict schema, 관찰 ID allowlist, 동의·예산·재시도.
- `detector.py`: anomalib 2.3.1 raw `PatchcoreModel`; 자동 datamodule/후처리 없음.
- `service.py`: 각 방식의 구성, 결합 정책, backend 측정 메타, cache, 최초 결과 보존.
- `experiments.py`: 동일 test ID, 진행 수, 중단, 예측 저장 후 evaluator 호출.
- `evaluation.py`: 정답 결합과 실패·보류 포함 지표, 실제 PatchCore 지도만 위치 평가.
- `storage.py`: 파라미터 바인딩 SQLite, 서버 생성 asset ID. dataset를 정적 mount하지 않음.

P0에는 torch import가 필요하지 않습니다. C/D에서만 선택 의존성을 로드합니다. detector artifact는 체크섬·split hash를 검증하고 `torch.load(weights_only=True)`로 로드합니다. 동결된 원본 query/참조/crop을 후속 질문에 재사용하고 정답·마스크는 제공하지 않습니다.

VLM의 observation이 JSON schema를 통과한 것은 구조 검증이며 사실 검증이 아닙니다. 설명의 수동 검토 결과는 최초 판정과 별도로 저장합니다.

## 보안·운영

서버 key만 사용. 저장 파일명은 서버 ID이며 경로 입력을 API에서 받지 않습니다. 업로드는 형식·디코딩·10MB·20M픽셀·단일 frame을 검사하고 EXIF를 제거합니다. 검증된 내부 PNG는 업로드 바이트 제한과 별도의 상한을 사용합니다. 외부 origin의 쓰기를 막고 CORS를 localhost로 제한합니다.

이 앱은 loopback 단일 사용자 연구 도구입니다. 인증, 다중 사용자 권한, TLS, 다중 backend worker, 분산 job queue는 범위 밖입니다. 외부에 공개하려면 별도 보안 설계가 필요합니다. API 실패 메시지는 키와 원시 외부 오류를 노출하지 않습니다.

프론트엔드의 선택적 WebMCP는 환경 상태 읽기·화면 이동만 제공합니다. 업로드·유료 검사·동의 설정 도구는 제공하지 않습니다. 미지원 브라우저에서는 조용히 비활성화됩니다.
