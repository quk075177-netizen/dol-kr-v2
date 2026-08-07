# 구현 문서

이 디렉터리는 현재 Twee 전처리 레이어의 정책과 계약을 담은 정본이다.

| 문서 | 내용 |
|---|---|
| [cst-scope.md](cst-scope.md) | 범위, lossless 원칙, 계층형 CST 모델, masking 경계 |
| [sugarcube-ground-truth.md](sugarcube-ground-truth.md) | SugarCube 원본과 대조할 parser/lexer 규칙 |
| [value-kind-policy.md](value-kind-policy.md) | `macro-value-kind.yml` 소비 규칙과 fail-safe |
| [validation.md](validation.md) | fixture, golden, round-trip, 결정성 검증 |
| [implementation-roadmap.md](implementation-roadmap.md) | 구현 단계, 모듈 책임, 단계별 완료 기준 |
| [parser-remediation-roadmap.md](parser-remediation-roadmap.md) | 검수 결과의 구조적 원인과 파서 개선 순서 |
| [parser-followup-agent-tasks.md](parser-followup-agent-tasks.md) | 병렬 후속 작업의 파일 범위와 완료 조건 |
| [cst-completion-plan.md](cst-completion-plan.md) | CST 완성 잔여 작업(T1~T3), 실행 순서, 워커 지시문 양식 |
| [worker-t2-value-kind-residual.md](worker-t2-value-kind-residual.md) | T2 워커 지시문: value-kind schema residual 정리 |
| [test-perf-analysis.md](test-perf-analysis.md) | 테스트 소요 시간 분석과 경량화 방안 |

`research/`는 vanilla/KO 대조, 호출부 분류, glossary 조사 같은 근거 자료와
생성 데이터셋을 보관한다. 정책이 과거 조사 문서와 다르면 이 디렉터리의
문서를 우선한다.
