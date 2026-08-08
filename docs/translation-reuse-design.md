# 번역 재사용성(Reuse) 설계

기준일: 2026-08-08
상태: **구현됨 (R1~R4, 2026-08-08)** — 등록 3,151건, 파일럿 재사용 검증 완료

## 목적

번역 결과물을 **저장·추적·재사용**한다. 같은 원문은 다시 번역하지 않고,
원문이 변경됐을 때만 해당 유닛을 재번역한다. 3-match 재사용(KO 기존 번역
승격)과 Gemini 신규 번역이 같은 저장소·같은 흐름을 쓰게 한다.

## 핵심 개념: 원문 해시 기반 식별

번역 유닛의 식별은 **원문 텍스트의 해시**다. 위치(span)는 원문이
조금만 바뀌어도 바뀌므로 재사용 키로 부적합하다.

| 키 | 용도 |
|---|---|
| `source_text_hash` (sha256 of masked_text) | **재사용 판정의 유일 키** |
| `unit_id` (source_path:passage:span) | 현재 위치 참조용 (재사용 키 아님) |
| `request_id` | 번역 요청(배치) 단위 추적 |

```text
translate(masked_text) → translated_text
reuse key = sha256(masked_text)
```

## 저장소 스키마 (번역 유닛 단위 JSONL)

`work/translations/translations.jsonl` (Git 제외):

```json
{
  "record_id": "tr_<hash 12자>_<seq>",
  "source_text_hash": "a1b2...",
  "source_text": "Hello there <000000>",
  "translated_text": "안녕하세요 <000000>",
  "source_path": "game/overworld-town/loc-cafe/main.twee",
  "passage_name": "Ocean Breeze",
  "unit_id": "loc-cafe:Ocean Breeze:1234",
  "request_id": "req_20260808_001",
  "model": "gemini-2.5-flash-lite",
  "temperature": 0.7,
  "created_at": "2026-08-08T06:00:00Z",
  "placeholder_ok": true,
  "post_status": "static_done | runtime_remaining | none",
  "source": "gemini | ko_reuse | owner_approved"
}
```

- `record_id`: 고유 레코드 ID — 재번역 시 **새 레코드**가 추가되고 이전
  레코드는 superseded 표시를 하지 않고 남긴다 (추적성).
- `source_text_hash`: 재사용 판정 키. source_text 전체를 sha256.
- `placeholder_ok`: restore 검증 통과 여부 (번역 시점에 확인).
- `post_status`: post 처리 상태 (정적 치환 완료 / 런타임 마커 잔존 / 해당 없음).
- `source`: `gemini`(신규), `ko_reuse`(3-match 승격), `owner_approved`(검수 승인).

## 재사용 판정 규칙

```text
input: passage → mask → chunk → unit(masked_text)

1. hash = sha256(unit.masked_text)
2. 저장소에서 hash 매칭 레코드 검색
   - 최신 레코드의 placeholder_ok == true and source != superseded
   → 그 translated_text 재사용 (번역 API 호출 없음)
3. 매칭 없음 → 번역 API 호출 → 새 레코드 저장
```

주의:

- **masked_text에 placeholder 토큰이 포함**되어 있으므로, 같은 문장이라도
  placeholder 번호가 다르면 hash가 다르다. placeholder 번호는 passage
  내 위치에 의존하므로 **passage가 바뀌면 재사용 불가** — 이건 의도된
  보수적 동작이다 (placeholder가 원본 매크로와 연결되므로 위치가
  바뀌면 복원 대상이 달라진다).
- 선택적 완화: placeholder 토큰을 `{P}`로 일반화한 hash를 보조 키로 두면
  "같은 문장 + 다른 매크로 위치" 재사용이 가능하다. 첫 구현에서는
  **완전 hash만** 사용하고, 일반화 hash는 후순위로 둔다.

## request_id 추적

`request_id`는 한 번의 배치 실행(파일럿/전체 corpus) 단위로 발급한다:

```text
req_<yyyymmdd>_<seq>
```

- 배치 시작 시 생성, 모든 레코드에 기록
- 동일 배치 재실행 시 새 request_id — 이전 배치 결과와 비교 가능
- 재번역 원인 조사용 (모델 변경/프롬프트 변경 시 이전 결과와 diff)

## 검수 → 승격 흐름

```text
Gemini 번역 (request_id 발급, source=gemini)
  → placeholder_ok 확인
  → post 정적 치환 적용 (post_status 기록)
  → 검수 (owner) → 승인 → source=owner_approved
```

- 승인 레코드는 재사용 우선순위가 가장 높다 (LLM 재번역보다 신뢰).
- 검수 전 레코드는 재사용 가능하되 "미검수" 상태로 표시한다
  (필요하면 `reviewed: bool` 필드).

## 3-match 재사용 통합

```text
corpus-triple-match.jsonl (KO body, 【 】마커 포함)
  → normalize_markers (【 】→{{post:...}})
  → resolve_static (정적 조사 확정)
  → source_text_hash = sha256(masked_text)
  → KO body의 번역 텍스트를 record로 등록 (source=ko_reuse)
  → 이후 같은 원문이 파이프라인에 들어오면 hash 매칭으로 재사용
```

- 마커 없는 44%(3,169 passage)부터 등록
- 마커 있는 56%는 동적 마커가 남은 상태로 등록 (post_status=runtime_remaining)
  → 게임 런타임 helper가 처리

## 구현 순서

### R1. 저장소 모듈 (`translation/store.py`) — 완료

- `load_translations(path)` → dict[hash, list[record]]
- `find_reuse(hash, records)` → 최신 유효 레코드 or None
- `find_passage_reuse(body_text, records)` → passage-level 조회
- `append_record(record, path)` → JSONL append
- `ko_body_preserves_skeleton(ko, signature)` → 보호 스팬 순서 보존 검사
- 유닛 테스트: hash 매칭, superseded 처리, 중복 append, skeleton 검사

### R2. 재사용 파이프라인 연결 — passage-level + unit-level 완료 (2026-08-08)

- `pilot.py --store PATH`: passage body hash 매칭 시 API 호출 없이
  `ko_reuse` 기록 사용, 미스 시 기존대로 번역
- 실측: "Adult Shop Lock" passage — REUSED, API 호출 0
- unit-level (`_reuse_unit`): 러너가 번역 전 각 유닛을
  `ko-units.jsonl`의 `source_text_hash`로 조회 — hit 시 저장된
  **복원형**(원문 바이트) `translated_text`를 현재 유닛 토큰으로
  재토큰화(`_retokenize`) 후 L1/L2 재검증, 통과 시 API 호출 없이 join.
  배치 모드는 재사용 유닛을 API 배치에서 제외하고 저장 텍스트를
  스플라이스. passage 레코드에 `reused_units` 필드 기록.
  - 토큰은 passage 내 위치로 재번호되므로 **토큰 형태 저장은 재사용
    불가** — 저장·재사용 모두 원문 바이트 기준 (수정/교차 passage hit).
  - 변경 검출: `translation/update_diff.py` — passage 분류(unchanged/
    changed/new) + 유닛별 재사용 가능 수 → `--targets`로 러너 입력 생성.

### R3. 3-match 등록 스크립트 (`translation/register_ko_reuse.py`) — 완료

- triple-match JSONL 전체(7,206 passage, 마커 유무 무관) → **우리 파서로
  source/KO 양쪽 합성 파일 파싱 → 보호 스팬 시퀀스 대칭 검사 +
  macro_sequence 대칭 검사** → `work/translations/ko-reuse.jsonl` 등록
  (Git 제외). 재실행 멱등 (기등록 hash는 already_registered).
- 등록: **7,137건** (마커 없음 3,157 + 마커 있음 3,978), 제외:
  skeleton_mismatch 58 + macro_sequence_mismatch 9 (링크 라벨 내부
  매크로 드롭 — 레거시 KO 결함. 파서 시그니처 검사로 안 잡히는 갭을
  macro_sequence 검사로 보완, 2026-08-08 발견·반영)
- 마커 있는 3,978건은 `post_status=runtime_remaining` — 레거시 【 】마커
  13,066개 전량이 런타임 값 앞에 있어 정적 치환 0건 (문서 §3.5의 91.8%보다
  실제는 100%). PO2 런타임 helper가 처리.
- game/ 실제 파일과 passage body hash 일치: 샘플 100/100

### R4. request_id — 완료

- `register_ko_reuse`는 `req_ko_reuse` 상수 사용
- 배치 실행 자동 발급(`req_<yyyymmdd>_<seq>`) — 러너 `next_request_id`

## 완료 기준

- [x] 같은 유닛 2회 번역 시 2회째는 API 호출 0 (저장소 hit) — passage-level 실측
- [x] 같은 유닛이 passage/수정을 넘어 재사용 — unit-level `_reuse_unit`
      (복원형 hash + `_retokenize`, L1/L2 재검증, 배치 포함, 2026-08-08)
- [x] 원문 변경 시 새 hash → 재번역
- [x] 3-match 마커 없는 passage가 재사용으로 처리됨
- [x] request_id로 배치별 번역 결과 추적 가능 (러너 자동 발급)
- [x] placeholder_ok=false 레코드는 재사용되지 않음

## 비용 효과 예상

- 3-match 마커 없는 3,169 passage의 유닛 수 × 유닛당 API 비용 절감
- 유닛 재방문(전체 corpus 재번역 시 동일 문장 반복) 절감
- 정확한 수치는 R2 구현 후 재사용 hit rate로 측정

## 참고

- 청킹: `docs/chunking-strategy.md` (masked_text = 재사용 키 원천)
- post: `docs/post-system-design.md` (post_status 연동)
- 3-match: `research/triple-match-and-post.md`
- 파일럿: `docs/pilot-report.md`