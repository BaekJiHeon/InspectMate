# InspectMate 검증 기록

최초 검증일: 2026-09-16. 실제 VLM 후속 확인: 2026-09-17. **코드·실행 흐름 검증이며 전체 제품 검사 성능 평가는 아닙니다.**

## 최신 게시 준비 확인 — 2026-09-17

- 현재 소스에서 `uv run --no-sync pytest -q`: **35 passed, 4 warnings, 5.79s**. 경고는 설치된 의존성의 deprecated API 관련이며 테스트 실패는 없습니다. 테스트에서 유료 VLM을 호출하지 않았습니다.
- `uv run --no-sync ruff check backend tests` 통과, `uv pip check`로 설치된 97개 패키지 호환 확인, `npm run build`의 TypeScript·Vite 빌드 통과.
- 최신 도록형 UI에서 실제 Hahmlet 로딩과 큰 제목·작은 글씨 적용을 확인했습니다. 실제 브라우저로 B/C 저장 결과 조회, 이미지·관찰·검토 목차 이동, 데스크톱 및 좁은 화면의 검사·이력·비교 실험 배치를 확인했습니다.
- [최신 GIF](docs/media/ATTRIBUTION.md)는 저장된 실제 B/C 검사 결과를 현재 UI로 조회한 설명용 재생입니다. 새 모델 추론·질문 전송·검토 저장은 수행하지 않았습니다. [촬영 기록](docs/evidence/catalog-replay-evidence.json).
- 아래 각 날짜의 검증 기록은 당시 수행 범위를 보존한 것입니다. 이전의 ‘브라우저 QA 미수행’ 표기는 해당 초기 단계의 기록이며 위의 후속 확인과 구분합니다.
- 전체 test 115장의 현재 A/B/C/D 비교 성능은 여전히 **미측정**입니다. 테스트 통과나 알려진 긁힘 한 장의 재확인이 전체 탐지 정확도를 뜻하지 않습니다.

## 실제 실행 결과

| 검증 | 결과 | 증거·범위 |
|---|---|---|
| Python 테스트 | **34 passed**, 4 warnings | `reports/verification-tests.xml`, 외부 유료 호출 없음 |
| Ruff | 통과 | `ruff check backend tests` |
| Frontend | TypeScript 및 Vite production build 통과 | `npm run build` |
| npm 의존성 검사 | 알려진 취약점 0건 보고 | `npm audit`, 검사 시점 기준 |
| Python 의존성 검사 | 설치된 97개 패키지 호환 | `uv pip check` |
| 로컬 HTTP | frontend/backend 응답 200 | `reports/live-smoke.json` |
| 명시적 데모 API 흐름 | 검사 → SQLite 저장 → 상세·이력 재조회 → 검토 메모 저장 통과 | 실제 로컬 서버 대상, 데모임을 응답에 표시 |
| 잘못된 이미지 | HTTP 422 거부 | 실제 로컬 서버 대상 |
| 초기 검증의 외부 요청 | **0회** | 2026-09-16 초기 검증 당시 서버 외부 전송 비활성 상태 |

경고는 Starlette/httpx, AnyIO의 deprecated API 각 1건 및 anomalib의 subsample_embedding 경고 2건입니다. 테스트 오류는 없었습니다.

## 테스트에서 확인한 핵심 조건

- RGB 픽셀 해시 기준 fit/calibration/test 분리, 중복 차단, fit에만 속하는 고정 참조.
- 정답·결함 경로·마스크를 추론 payload에서 제외. evaluator 정답 변경 시 payload 불변. A/B의 차이는 정상 참조 입력뿐.
- **실제 anomalib CPU 코드**로 무작위 backbone·64px 테스트용 도형의 특징 메모리와 calibration 구축, 저장·로드 후 점수와 지도 일치.
- 위 smoke를 test 입력만 바꾸어 다시 구축했을 때 fit/calibration ID·점수·이미지 임계값·픽셀 임계값·heatmap 범위 불변.
- 비정방형 이미지 지도·ROI를 원본 좌표로 복원. 빈 지도에서 ROI를 생성하지 않음.
- 설치한 OpenAI SDK의 Responses 요청 직렬화와 strict JSON Schema를 mock HTTP transport로 검증. 잘린 출력·refusal·스키마 오류·허용되지 않은 이미지 ID 거부.
- 키·서버 설정·요청 동의 게이트, 재시도 포함 요청 한도, 취소 후 추가 호출 차단, 실제 사용량 미제공 처리.
- A/B 같은 sample ID의 batch 실행·저장·별도 평가. 실패·취소한 행 보존. 평가 재생성 시 exploratory 표시 보존.
- 판단 보류·실패를 포함한 지표 분모, selective subset, 데모 평가 차단.
- D의 detector/VLM/결합 판정 분리. detector 정상·ROI 없음에도 VLM 실행. 후속 질문이 최초 판정을 덮어쓰지 않음.
- 업로드·검사·저장·이력·캐시·서버 재시작 시 미완료 기록 처리.

생성된 테스트 이미지, mock 응답, 무작위 가중치 smoke는 테스트 전용입니다. MVTec 데이터로 표현하지 않으며 정식 평가에 포함하지 않습니다. 무작위 가중치 산출물은 실제 검사에서 차단합니다.

## 아직 실행 검증하지 못한 부분

1. 실제 MVTec metal_nut의 전체 test 성능 평가. manifest 생성과 pretrained PatchCore fit/calibration은 아래 후속 작업에서 완료했습니다.
2. 실제 이미지에 대한 관찰·추천 조치 내용의 체계적인 정확성 평가, 다른 계정·모델의 접근 권한. 현재 계정의 실제 B 정상 예제 호출 및 B/D 흠집 예제 호출은 아래와 같이 확인했습니다.
3. 실제 A/B/C/D 성능 비교·지연시간·비용·결함 위치 품질과 설명 수동 평가.
4. 브라우저의 시각적·클릭 기반 QA 및 선택적 WebMCP runtime.

따라서 `reports/current/`의 성능 상태는 **not_run / 미측정**입니다. predictions는 비어 있으며 CSV는 헤더만 있습니다. 모델 성능이나 향상률을 만들지 않았습니다.

## 후속 실제 데이터 준비 — 2026-09-16

- 공개 미러의 metal_nut 아카이브 165,414,484 bytes를 다운로드하고 게시된 SHA256과 일치함을 확인했습니다. 원본 라이선스·README와 출처를 보존했습니다.
- 실제 정상 학습 이미지 220장, test 115장(정상 22 / 이상 93), 마스크 93장을 검증했습니다.
- 고정 manifest: fit 176 / calibration 44 / test 115. 정상 참조는 fit에서 1장입니다.
- **Pretrained resnet18 / 256px / CPU**, memory bank 18,022개 특징으로 실제 PatchCore 구축·calibration을 완료했습니다. 초기 프로토콜과 임계값 규칙을 변경하지 않았습니다.
- 예제 5장의 실제 업로드 → C 검사 → 저장·재조회 → heatmap 조회 결과는 [실행 기록](reports/data-preparation.json)에 기록합니다. 외부 VLM 요청은 0회입니다.
- 이 예제들은 사용법 확인을 위해 선택한 탐색용 이미지이며, 정식 전체 비교 평가나 모델 성능 보증으로 사용하지 않습니다. 테스트 결과에 맞춘 임계값 조정은 하지 않았습니다.
- 실제 한계 사례: scratch 정답인 `example_05.png`를 C가 normal로 판정했습니다. 실행 성공과 정확한 판정을 구분하며, 이 사례를 숨기거나 임계값을 조정하지 않았습니다.

## 검증 환경

- macOS 26.5.2 arm64, Python 3.11.15, Node 26.7.0, npm 11.19.0.
- FastAPI 0.141.1, Pydantic 2.13.5, OpenAI SDK 2.54.0.
- anomalib 2.3.1, PyTorch 2.8.0, torchvision 0.23.0, timm 1.0.29, CPU.
- React 19.1.1, TypeScript 5.9.2, Vite 7.3.6.
- 재설치 기준은 `uv.lock`, `frontend/package-lock.json`입니다.

## 실제 B 검사 확인 — 2026-09-17

- 사용자가 저장한 `.env`의 키·외부 호출 설정을 값 노출 없이 확인하고, 서버를 재시작했습니다.
- 공개 정상 너트 예제 한 장과 fit에서 고정 선택한 정상 참조 한 장으로 `vlm_reference` 검사를 실행했습니다. 사용자의 서버 재시작·동작 확인 요청에 따라 이번 실행에 동의 값을 전달했습니다.
- `gpt-4.1-mini-2025-04-14`, 실제 외부 요청 **1회**, 재시도 **0회**, 캐시 미사용, 데모 아님.
- 응답 구조 검증·SQLite 저장·동일 결과 재조회 성공. 모델 판정은 normal, 측정 지연시간은 약 **4.73초**였습니다.
- 실제 API usage: 입력 2,097 / 출력 121 / 합계 2,218 토큰. 단가를 설정하지 않아 비용은 미산정입니다.
- [호출 원문·실행 기록](reports/live-vlm-verification.json). 응답의 추천 조치에는 추가 검토 없이 통과할 수 있다는 표현이 포함됐으며, 그 적절성은 검증되지 않았습니다. 연구용 관찰 결과를 실제 출하 승인으로 해석해서는 안 됩니다.
- 이번 단일 확인은 전체 A/B/C/D 성능 평가나 설명 정확성 검증이 아닙니다. 초기 테스트 보고서와 2026-09-16의 외부 요청 0회 기록은 당시 사실로 보존합니다.

## 서비스 진단 화면 및 B/D 흠집 검사 — 2026-09-17

- C/D 결과에 원본·실제 이상 지도·ROI를 나란히 표시하고, 저장된 calibration 점수 분포와 이미지/위치별 기준을 분리해 보여줍니다. 정상+ROI의 경우 재검토 안내를 추가하며 저장 판정·모델·임계값은 변경하지 않았습니다.
- A/B·데모·점수 없는 기록에서 패널 숨김, 실제 C/D 기록의 44개 정상 점수·검사 점수·기준값 표시, metadata 누락·동일 점수 범위 처리를 React 서버 렌더링으로 확인했습니다. TypeScript/Vite build 통과. 원본·지도 HTTP 200 및 700×700 좌표계 일치 확인. 브라우저 클릭·시각 QA는 수행하지 않았습니다. [UI 검증 기록](reports/diagnosis-ui-verification.json).
- 사용자의 실제 VLM 테스트 요청에 따라 동일 scratch 입력으로 **B/D 각각 실제 외부 요청 1회**, 캐시 미사용, 재시도 0회, 모델 `gpt-4.1-mini-2025-04-14`를 실행했습니다. 정답·마스크를 모델에 제공하지 않았습니다.
- B: 정상 참조 1장 포함, 모델 normal. “긁힘이 없다”는 설명은 이 사례의 원본 정답과 맞지 않습니다. 약 3.39초, 2,227 토큰.
- D: 원본+같은 정상 참조+실제 ROI crop 1개 포함, PatchCore normal / VLM normal / 최종 normal. VLM이 하단 오른쪽 긁힘을 언급했지만 정상 변동으로 해석하여 불량을 놓쳤습니다. 약 3.58초(VLM 호출), 2,290 토큰.
- 두 호출 모두 응답 검증·저장·재조회 성공. **연결 성공과 결함 검출 성공은 별개이며 이번 두 판정은 모두 미탐**입니다. [실행 원문](reports/live-vlm-scratch-verification.json). 총 4,517 토큰, 단가 미설정으로 비용 미산정. 추가 호출이나 이 사례에 맞춘 프롬프트 조정은 하지 않았습니다.

## 판정 기준 보완 및 디자인 변경 — 2026-09-17

- 새 초기 프롬프트 `inspection-v2-observation-first` / 기준 `appearance-v2-observation-first`는 관찰과 허용 기준을 구분합니다. 공통 지시 변경으로 후속 버전도 `followup-v3-observation-criteria`로 기록합니다. 모델·PatchCore 임계값·D 결합 규칙·과거 판정은 보존했습니다.
- 기존 실제 B 입력에서 새 cache key가 이전과 다름을 확인했습니다. 새 검사는 이전 기준의 잘못된 응답 캐시를 재사용하지 않습니다.
- 검토 상태를 검사 상세·이력에서 먼저 표시하고 모델 원시 판정을 분리했습니다. 설명 품질 검토를 제품 합격으로 표시하지 않습니다. 상세를 열 때 현재 기록을 조회하여 오래된 실험 스냅샷의 검토 상태가 최신 메모를 덮어쓰는 경로도 방지했습니다.
- 상단 탐색 메뉴, 네이비/흰색/빨강, 각진 패널과 제목 계층으로 테마를 변경했습니다. 업로드·비교·이상 지도·질문·실험 기능을 유지했습니다.
- Python 전체 **35 passed**, Ruff 통과, TypeScript/Vite build 통과. React 렌더링·상태 정책 11가지와 실제 B/C/D 기록을 검증했습니다. 브라우저 시각·클릭 QA는 수행하지 않았습니다. [코드 테스트](reports/observation-policy-tests.xml), [화면 로직 검증](reports/professional-redesign-verification.json).
- 같은 알려진 scratch 사례를 새 B 기준으로 실제 1회 재검사하여 **defect_suspected** 응답을 받았습니다. 중앙 하단의 긁힘 같은 손상과 깊이·허용 기준의 불확실성을 설명했습니다. 요청 1회, 재시도 0, 캐시 없음, 2,633 토큰, 약 4.37초. [원문](reports/observation-policy-live-check.json).
- 피드백을 반영한 뒤 같은 사례를 다시 본 **탐색 확인**이며 독립 평가나 전체 성능 향상의 증거가 아닙니다. 별도 평가 데이터에서 불량 미탐·정상 오탐·보류를 함께 확인해야 합니다.

## 재실행

### 후속 질문의 기존 판정 고정 지시 수정 — 2026-09-17

- 사용자 첨부 답변과 일치하는 B 검사 `2694ed209f4f4b70987b80ae58a61c35`의 후속 질문을 확인했습니다. 흠집 원본과 정상 참조는 모두 700×700, high detail로 전달됐으며 B이므로 ROI는 없습니다. 초기 B 결과는 캐시 재사용, 후속 답변 자체는 새 API 호출입니다.
- 이전 구현은 초기 결과 전체(정상 판정·요약·권고 포함)를 후속 입력으로 보내고 최초 판정을 유지하라고 지시했습니다. 저장 기록 불변성과 모델의 사실 정정을 혼동한 지시를 제거했습니다.
- 후속 질문은 이전 관찰만 검증되지 않은 문맥으로 제공하고, 이미지를 다시 관찰하여 이전 설명이 틀리면 정정하도록 변경했습니다. 보이지 않는 깊이·허용 기준을 추정하지 않고 관찰 불확실성을 구분하도록 했습니다. 후속 버전은 `followup-v2-independent-observation`이며 원래 검사 버전도 함께 기록합니다.
- 최초 검사 프롬프트·모델·PatchCore·임계값·기존 판정 및 질문 기록은 변경하지 않았습니다. 기존 잘못된 초기 검사 캐시도 이 수정으로 정확해지지 않습니다.
- 관련 mock/저장 테스트 **22 passed**, Ruff 통과. 전송 이미지 bytes 보존, 기존 판정 반복 제외, 관찰 정정 응답 허용, 원본 검사 기록 불변성을 검증했습니다. [테스트 기록](reports/followup-reliability-tests.xml).
- 이번 수정 후 유료 VLM 호출은 하지 않았습니다. 프롬프트 결함 수정이며 실제 관찰 정확도 개선은 아직 검증되지 않았습니다.

```bash
uv run --no-sync pytest -q --junitxml=reports/verification-tests.xml
uv run --no-sync ruff check backend tests
uv pip check
cd frontend
npm run build
npm audit
```

실제 모델 평가에 필요한 데이터 준비·서버 설정·명시적 전송 동의는 [README](README.md)를 따르세요.
