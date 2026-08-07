# 구현 문서

이 디렉터리는 Twee 전처리·번역 파이프라인의 **정책과 현행 계약**을 담은
정본이다. `docs/archive/`는 완료된 작업의 기록을 보관한다.

## 정본 (현행 정책)

| 문서 | 내용 |
|---|---|
| [cst-scope.md](cst-scope.md) | 범위, lossless 원칙, 계층형 CST 모델, masking 경계 |
| [sugarcube-ground-truth.md](sugarcube-ground-truth.md) | SugarCube 원본과 대조할 parser/lexer 규칙 |
| [value-kind-policy.md](value-kind-policy.md) | `macro-value-kind.yml` 소비 규칙과 fail-safe |
| [validation.md](validation.md) | fixture, golden, round-trip, 결정성 검증, 현재 기대값 |

## 현행 설계·구현

| 문서 | 내용 |
|---|---|
| [chunking-strategy.md](chunking-strategy.md) | 번역 유닛 분할(청킹) — 구현 완료, 현행 동작 |
| [post-system-design.md](post-system-design.md) | post(조사) 시스템 — 설계 + 초기 구현 |
| [translation-reuse-design.md](translation-reuse-design.md) | 번역 재사용 저장소 — 설계 (미구현) |
| [translation-pipeline-roadmap.md](translation-pipeline-roadmap.md) | 현행 로드맵: 파일럿 → post → 3-match 재사용 |
| [g-l-macro-investigation.md](g-l-macro-investigation.md) | g/l 매크로 조사 — 진행 중 (statDisplay.create 확정, exit 미해결) |
| [triple-match-and-post.md](triple-match-and-post.md) | 3-way match 골든 + post(조사) 정보 취합 |

## 아카이브 (완료 기록)

[`docs/archive/`](archive/README.md) — 완료된 로드맵·워커 지시문·감사/검수
보고서·피드백 트리아지. 참고용이며 현행 정책이 아니다.

- `implementation-roadmap.md` — 초기 구현 단계 (1~6, 완료)
- `cst-completion-plan.md` — CST 완성 계획 (T1~T3, 완료)
- `parser-remediation-roadmap.md` — 파서 구조 개선 (완료)
- `parser-followup-agent-tasks.md`, `worker-*.md` — 워커 지시문 (일회성)
- `macro-grammar-audit.md`, `value-kind-audit-*.md` — 감사·검수 보고서
- `macro-value-kind-residual-report.md` — residual 보고서
- `feedback-issue-triage.md`, `system-review-triage.md` — 피드백 기록
- `test-perf-analysis.md` — 테스트 성능 분석
- `pilot-report.md` — 파일럿 배치 결과
- `semantic-role-roadmap.md` — 시맨틱 롤 (보류)
- `system-review-brief.md` — 점검용 브리프

`research/`는 vanilla/KO 대조, 호출부 분류, glossary 조사 같은 근거 자료와
생성 데이터셋을 보관한다. 정책이 과거 조사 문서와 다르면 이 디렉터리의
문서를 우선한다.