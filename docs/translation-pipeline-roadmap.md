# 번역 파이프라인 로드맵 (파일럿 확대 → post → 3-match 재사용)

기준일: 2026-08-08
상태: 진행 중

## 현재 위치

```text
CST 파서 (완료) → value-kind 분류 (완료, unclassified 0) → 청킹 (완료)
  → 파일럿 번역 (기본 동작 확인됨)
```

확인된 사실:

- Gemini 2.5 Flash Lite + ADC 인증, SDK 방식으로 번역 동작
- placeholder 보존 28/28, restore 정상 (번역 전 byte-exact는 기존 검증됨)
- **SOV/SVO 어순 변환은 LLM이 처리** — 시맨틱 롤 불필요
- 시맨틱 롤/post가 필요한 상황: **매크로가 문장을 조각조각 조립**할 때
  (`<<he "Robin">>가 말했다`, `$worn.upper.name【은는】`) — 런타임 조립 문제
- 3-match 재사용: 마커 없는 44%는 즉시 가능, 마커 있는 56%는 post 시스템 후
  (마커의 91.8%가 런타임 값 앞 → 동적 처리 필요)

## 목표

1. **파일럿 확대**: passage 유형별(대화/전투/성인/UI/설정) 번역 품질을
   확인하고, "매크로 조각 삽입으로 번역이 어색해지는 실제 사례"를 수집
2. **post(조사) 시스템 설계**: getPostNum + 정적/동적 치환 + glossary 연동
3. **3-match 재사용**: post 완성 후, 마커 없는 44%부터 데이터 레이어 승격
4. **시맨틱 롤**: 파일럿에서 실패 사례가 나오면 도입 (지금은 보류)

## 단계

### P1. 파일럿 확대 (직접 진행)

passage 유형별 샘플 번역을 돌려 품질을 기록한다.

- 유형: 대화(loc-cafe), 전투(base-combat), 성인 콘텐츠, UI 설정(01-config),
  이벤트(overworld-*)
- 각 유형 1 passage, 전체 유닛 번역 (보통 10~60 유닛)
- 기록: placeholder 보존률, restore 성공, 번역 품질 평가(직접), 문제 사례

완료 기준:

- 유형별 1개씩 총 5개 passage 파일럿 완료
- placeholder 보존률 ≥ 95% (재시도 로직 포함)
- **매크로 조각 삽입으로 번역이 어색해진 사례 목록** (있으면 sample 텍스트,
  없으면 "없음" 명시)
- 결과를 `docs/pilot-report.md`에 기록

### P2. post(조사) 시스템 설계 문서 (직접, 구현 전)

구현 전 설계 문서를 작성한다. `research/triple-match-and-post.md`의
Part 2를 기반으로 구현 설계로 구체화한다.

- `getPostNum` 규칙 (한글/숫자/라틴) — 이미 확정
- 정적 치환: 마커 앞이 고정 문자열 → 번역 빌드 타임에 확정 조사
- 동적 치환: 마커 앞이 런타임 토큰 → particle helper (게임 런타임)
- glossary 연동: `(slot, key) → display_ko + post` → 조사 선택
- 시맨틱 롤이 필요한지 여부 판정 기준 명시

완료 기준:

- `docs/post-system-design.md` 작성
- 정적/동적 판정 기준, glossary 연동 방식, 시맨틱 롤 판정 기준 포함

### P3. 3-match 재사용 데이터 승격 (post 완료 후)

post 시스템 구현 완료 후 진행.

- 마커 없는 3,169 passage (44%): 먼저 데이터 레이어로
- 마커 있는 4,037 passage: post 처리 후 승격
- 참고 번역 용도(few-shot/QA)로는 지금도 사용 가능 — 문서에 명시

완료 기준:

- 재사용 passage의 KO body에서 `【 】` 마커 0개
- 번역 결과물이 파이프라인 출력과 동일한 스키마

### P4. 파일럿 결과 기반 시맨틱 롤 판정 (P1 이후)

- P1에서 "매크로 조각 삽입으로 어색한 번역" 사례가 나오면:
  → 시맨틱 롤 설계 문서 작성 (`docs/semantic-role-roadmap.md` 갱신)
- 사례가 없으면: 시맨틱 롤은 보류, post 시스템만 진행

## 실행 순서

```text
P1 파일럿 확대 ────────────┐
                          ├─ P2 post 설계 (병렬 가능)
P1 완료 → P4 시맨틱 롤 판정 │
                          └─ P3 3-match 재사용 (post 구현 후)
```

P1과 P2는 독립이므로 병렬 진행 가능. P4는 P1 결과에 의존. P3는
post 구현에 의존 (P2 설계 후 구현 단계).

## 하지 않을 일 (현재 단계)

- 시맨틱 롤 구현 (사례가 나오기 전까지)
- 3-match 전량 재사용 (post 전)
- glossary 전 분야 확장 (clothing 외) — props/색상/식물은 후순위
- 번역문 저장소/버전 관리 설계 (파일럿 결과물 규모 확인 후)

## 참고 문서

- `docs/chunking-strategy.md` — 청킹 설계/구현
- `docs/cst-completion-plan.md` — CST 완성 계획
- `docs/value-kind-audit-roadmap.md` — value-kind 검수
- `docs/semantic-role-roadmap.md` — 시맨틱 롤 조사 (보류 중)
- `research/triple-match-and-post.md` — 3-way match/post 정보 취합
- `research/ko-marker-analysis.md` — 【 】마커 분석