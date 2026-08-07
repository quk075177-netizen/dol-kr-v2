# DoL Korean Pre-Translation CST

현재 Plus `game/`의 Twee 원문을 번역 전에 안전하게 분해하기 위한 개인
프로젝트다.

현재 목표는 다음 네 단계다.

1. Twee 파일을 passage 단위로 lossless 분리
2. SugarCube 매크로와 인자를 UTF-8 byte span으로 스캔
3. 계층형 CST로 매크로·조건부 블록·텍스트 segment의 부모 관계 보존
4. `prose_text`만 노출하고 나머지는 placeholder로 마스킹한 뒤 즉시 복구

번역 API, 번역문 삽입, QA, JavaScript 처리는 현재 범위에 없다. JavaScript는
Twee 레이어가 안정된 뒤 별도 frontend로 검토한다.

## 문서

- [CST 범위와 데이터 모델](docs/cst-scope.md)
- [SugarCube ground truth 대조 규칙](docs/sugarcube-ground-truth.md)
- [value-kind와 fail-safe 정책](docs/value-kind-policy.md)
- [검증과 완료 조건](docs/validation.md)
- [문서 인덱스](docs/README.md)

조사 원문과 생성된 데이터셋은 [research/](research/)에 보관한다. `research/`
문서는 근거와 과거 분석 기록이며, 구현 정책의 정본은 `docs/`다.

## 상태

계층형 CST 요구사항을 반영해 parser 구현을 재설계하는 중이다. 기존
flat-list WIP는 검증되지 않은 초안으로 취급한다.
