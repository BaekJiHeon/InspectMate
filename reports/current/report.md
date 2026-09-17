# InspectMate actual evaluation status

**미실행 · 성능 미측정.**

실제 MVTec metal_nut 데이터 설치와 pretrained PatchCore fit/calibration을 완료했고, 2026-09-17 실제 B 검사 1건의 API 응답·저장·재조회를 별도로 확인했습니다. 전체 A/B/C/D 비교 평가는 미실행입니다. C의 선택 예제 확인은 ../data-preparation.json, B의 실제 호출 확인은 ../live-vlm-verification.json에 기록하며, 이를 정확도·개선율·비용 절감률로 표현하지 않습니다.

`predictions.jsonl`은 비어 있고 `comparison.csv`는 헤더만 있습니다. `metrics.json`은 명시적 not_run/null 상태입니다. 이는 실제 추론 결과 파일이 아니라 미실행 상태를 전달하는 산출물입니다.

단위 테스트와 별도의 실제 호출 검증 범위는 ../../verification.md에 기록됩니다. 테스트의 generated fixtures / mock responses / random-backbone smoke를 정식 benchmark에 포함하지 않습니다.
