# 미디어 출처와 이용 조건

이 폴더의 GIF·데이터 갤러리 및 `reports/patchcore-scratch-diagnosis/diagnosis.png`에는 **MVTec AD**의 금속 너트 이미지가 포함됩니다.

- 원저작자: **© 2019 MVTec Software GmbH**.
- 원 데이터: [MVTec Anomaly Detection](https://www.mvtec.com/research-teaching/datasets/mvtec-ad).
- 이용 조건: **Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0)**. [원문 사본](MVTec-AD-CC-BY-NC-SA-4.0.txt) · [라이선스 안내](https://creativecommons.org/licenses/by-nc-sa/4.0/).
- 논문: Paul Bergmann, Michael Fauser, David Sattlegger, Carsten Steger, *A Comprehensive Real-World Dataset for Unsupervised Anomaly Detection*, CVPR 2019.

## 이 저장소에서 추가한 내용

GIF는 실제 InspectMate 서비스의 화면 캡처를 순서대로 연결하고 한국어 설명과 장면별 재생 시간을 추가한 자료입니다. 원본 제품 사진 위에 보여 주는 이상 지도와 후보 박스는 별도의 표시 층입니다. 데이터 갤러리에는 한국어 캡션과 배치를 추가했습니다. 진단 그림에는 정답 윤곽·모델 지도·후보 박스·점수 분포를 설명용으로 배치했습니다.

이 파생 설명 미디어는 **CC BY-NC-SA 4.0**으로 제공합니다. 프로젝트 코드의 MIT 라이선스는 MVTec 데이터나 이를 포함한 미디어에 적용되지 않습니다. 이 저장소에 전체 데이터셋이나 모델 가중치를 포함하지 않습니다.

## GIF가 보여 주는 실제 기록

| 파일 | 원검사 기록 | 새 GIF의 범위 |
|---|---|---|
| `vlm-workflow-catalog.gif` | 2026-09-17 15:04:12 KST · B · `94f79c2c68a84e4da9c2f5019703ad97` | 저장된 VLM 결과 조회·이미지 비교·관찰·검토 양식 |
| `patchcore-workflow-catalog.gif` | 2026-09-17 15:02:27 KST · C · `6280e7dc8c344273b32413a5af374a05` | 저장된 PatchCore 결과 조회·후보·미탐 근거·점수 분포 |

현재 도록형 UI로 촬영한 **저장 결과 재생**입니다. 새 추론·후속 질문 전송·검토 저장을 수행한 장면이 아니며 GIF 재생 길이는 모델 응답 시간이 아닙니다. 원검사 증빙과 GIF 해시는 [실행 증빙](../evidence/execution-evidence.json), [촬영 증빙](../evidence/catalog-replay-evidence.json)에 있습니다.

두 GIF의 검사 사진은 `metal_nut/test/scratch/000.png`이며 B의 정상 참조는 `train/good/080.png`입니다. `data-examples.png`는 test의 정상·변형·변색·뒤집힘·긁힘 원본 각 1장과 긁힘 정답 마스크 1장을 보여 줍니다. 정답 마스크는 모델 입력이 아닙니다.

화면의 Hahmlet 글꼴은 [SIL Open Font License 1.1](../../frontend/public/fonts/Hahmlet-OFL.txt)에 따릅니다.
