# 처음 실행하고 너트 이미지를 검사하기

이 저장소에는 코드와 설명용 GIF·갤러리가 들어 있습니다. 원본 데이터셋, 정상 특징 메모리, 업로드 파일, SQLite 검사 이력은 각자의 로컬 환경에서 준비합니다. 문서의 기존 검사 ID는 제작 당시 실행 증빙이며 새 설치의 이력에 자동으로 생기지 않습니다.

## 1. 화면부터 실행하기

Python 3.11 또는 3.12, uv, Node 20.19+ 또는 22.12+, npm을 준비한 뒤 프로젝트 루트에서 실행합니다.

```bash
uv sync --locked --python 3.11
cd frontend
npm ci
cd ..
cp .env.example .env
bash scripts/dev.sh
```

[검사 화면](http://127.0.0.1:5173/)에서 **데모 모드 → 데모 샘플 불러오기 → 검사 실행**을 선택하면 API 키·데이터셋 없이 화면과 저장 흐름을 확인할 수 있습니다. 데모는 전용 도형을 사용하며 실제 이상탐지가 아닙니다.

## 2. 실제 MVTec AD 이미지 준비

[MVTec AD 공식 페이지](https://www.mvtec.com/research-teaching/datasets/mvtec-ad)의 `metal_nut`를 받아 다음과 같이 배치합니다. 원본 라이선스와 출처 파일도 보존하세요. 수량과 분할은 [데이터 카드](data_card.md)에 있습니다.

```text
datasets/mvtec_ad/metal_nut/
  train/good/*.png
  test/good/*.png
  test/bent/*.png
  test/color/*.png
  test/flip/*.png
  test/scratch/*.png
  ground_truth/<type>/*_mask.png
```

서버를 실행한 터미널과 별도의 터미널에서 프로젝트 루트로 이동한 뒤:

```bash
uv sync --locked --python 3.11 --extra detector
uv run --no-sync inspectmate manifest --root datasets/mvtec_ad --category metal_nut
uv run --no-sync inspectmate detector-fit --category metal_nut
```

첫 detector 준비에는 사전학습 backbone 다운로드와 정상 특징 계산이 필요합니다. 정상 220장을 fit 176장·calibration 44장으로 나누며, test 115장과 정답 마스크는 특징 구축에 쓰지 않습니다. 정상 참조도 fit에서 자동 선정합니다. 이미 manifest를 만들었다면 중복 생성하지 마세요.

## 3. 어떤 사진을 올릴까?

다음 경로는 데이터 다운로드 후 생기는 파일입니다.

| 검사 사진 | 데이터셋 정답 |
|---|---|
| `datasets/mvtec_ad/metal_nut/test/good/000.png` | 정상 |
| `datasets/mvtec_ad/metal_nut/test/bent/000.png` | 형상 변형 |
| `datasets/mvtec_ad/metal_nut/test/color/000.png` | 색상 이상 |
| `datasets/mvtec_ad/metal_nut/test/flip/000.png` | 뒤집힘 |
| `datasets/mvtec_ad/metal_nut/test/scratch/000.png` | 긁힘 |

제작 환경의 `example_01.png`부터 `example_05.png`는 이 다섯 사진을 순서대로 복사한 별칭입니다. 별칭 파일은 저장소에 포함되지 않습니다. 위 원본을 그대로 사용하면 됩니다.

**정답 마스크, GIF, 박스가 그려진 진단 그림은 검사 입력으로 올리지 마세요.** 표시를 추가하지 않은 제품 사진 PNG/JPG/WEBP 한 장, 최대 10MB를 사용합니다.

## 4. C · PatchCore로 검사하기

1. 새로고침하고 **실행 모드: 실제 모델**, **검사 방식: C · PatchCore**를 선택합니다.
2. 사진을 **검사 이미지** 영역에 끌어 놓거나 **이미지 업로드**로 선택합니다.
3. 이미지 바로 아래의 **검사 실행**을 누릅니다. 비활성화된 경우 버튼 아래 이유를 확인합니다.
4. 원본·이상 지도·의심 영역과 이미지 점수·판정 기준을 확인합니다. C는 OpenAI API를 호출하지 않습니다.
5. **검사 이력**에서 같은 결과를 다시 열거나 **검사자 재검토**에 메모를 저장합니다.

긁힘 예시 `test/scratch/000.png`는 제작 환경의 C에서 정상으로 분류됐습니다. 이미지 점수 11.861이 기준 12.093을 넘지 않았지만 국소 후보는 검출됐으므로 화면은 **의심 영역 검토 필요**로 안내합니다. [미탐 분석](reports/patchcore-scratch-diagnosis/review.md)에서 근거를 볼 수 있습니다. 새 환경의 모델 준비 결과는 설치·연산 환경에 따라 달라질 수 있습니다.

## 5. A/B/D · VLM 사용하기

서버 전용 `.env`에 `OPENAI_API_KEY`, `ALLOW_EXTERNAL_API=true`를 설정하고 서버를 다시 시작합니다. 상세 설정은 [README](README.md)를 따르세요. 화면에서 **이번 실행의 이미지 전송·유료 호출에 동의**한 뒤 검사합니다.

| 방식 | 이미지 표시 | 추가 준비 |
|---|---|---|
| A | 검사 이미지 | OpenAI API 설정 |
| B | 왼쪽 검사 이미지 · 오른쪽 정상 참조 | API 설정 + manifest |
| C | 검사 이미지 | manifest + PatchCore 특징 메모리 |
| D | 왼쪽 검사 이미지 · 오른쪽 정상 참조 | API 설정 + manifest + PatchCore 특징 메모리 |

B/D의 참조 사진은 자동으로 불러옵니다. A/B에는 PatchCore 진단 패널이 없고, C에는 VLM 후속 질문·API 동의·토큰·비용 항목이 없습니다.

## 6. 결과를 읽는 순서

최신 화면은 **금속 너트 외관 이상탐지**를 제목으로 사용하는 도록형 UI이며, 큰 제목부터 작은 설명까지 Hahmlet 서체를 적용했습니다.

1. **이미지 비교:** 제품 원본과 필요한 경우 정상 참조를 확인합니다.
2. **관찰 내용:** 검사자의 검토 상태, 모델 원시 판정, 관찰 근거와 불확실성을 차례로 봅니다. C/D는 이미지 전체 기준과 국소 영역 기준을 구분합니다.
3. **검토 기록:** VLM 추가 질문과 검사자의 설명 품질 평가·메모를 별도로 기록합니다. 후속 답변은 최초 판정을 덮어쓰지 않습니다.

모델 정상은 제품 합격 승인이 아닙니다. 새로운 사진 업로드는 재학습도 아닙니다. 이미 본 예시를 바탕으로 설정을 고친 결과는 탐색 확인이며 독립 평가 정확도로 표현하지 않습니다.

## 서버 다시 켜기

프로젝트 루트에서 `bash scripts/dev.sh`를 실행합니다. 이미 실행 중이면 브라우저를 새로고침하면 됩니다. API 키, 데이터, 이력과 가중치는 `.gitignore`에 의해 Git에서 제외됩니다.
