# 번역 스토어 스키마 (레코드 필드 참조)

정본: `work/translations/ko-reuse.jsonl` (JSONL — 레코드 1줄 = 1객체).
어셈블러/러너/스모크가 읽는 유일한 소스.

## 레코드 유형

| `source` | 생성 주체 | 추가 필드 |
|---|---|---|
| `ko_reuse` | `register_ko_reuse` (3-match 등록) | (공통만) |
| `gemini` | `translate_passages` (러너) | `repaired` `l2_retries` `api_calls` `escalated` `escalated_units` `tier` |

## 공통 필드

| 필드 | 타입 | 설명 |
|---|---|---|
| `record_id` | string | `tr_<hash12>_ko` / `tr_<hash12>_gemini` — 고유 레코드 ID |
| `source_text_hash` | string | sha256(원문 body) — **재사용 판정의 유일 키** |
| `source_text` | string | 원본 passage body (경계 개행 포함) |
| `translated_text` | string | 한국어 body (ko_reuse는 match_boundaries 개행 정규화) |
| `source_path` | string | game-root 상대경로 (`overworld-town/...`, `game/` 접두어 없음) |
| `passage_name` | string | passage 이름 |
| `unit_id` | string | `{source_path}:{passage_name}` — 위치 참조용 (재사용 키 아님) |
| `request_id` | string | `req_<yyyymmdd>_<seq>` — 배치 단위 추적 |
| `model` | string | `ko_reuse` / `gemini-2.5-flash-lite` / `gemini-2.5-flash` / ... |
| `temperature` | number\|null | LLM temperature (ko_reuse = null) |
| `created_at` | string | KST ISO (`2026-08-08T12:00:00+09:00`) |
| `placeholder_ok` | boolean | placeholder 복원 검증 통과 여부 (false면 재사용 안 됨) |
| `post_status` | string | `none` / `static_done` / `runtime_remaining` |
| `source` | string | `ko_reuse` / `gemini` |
| `level` | string | `passage` (현재 전부) |

### post_status 의미

| 값 | 의미 |
|---|---|
| `none` | 마커 없음 — 그대로 사용 |
| `static_done` | 마커 있었고 전부 정적 치환됨 |
| `runtime_remaining` | 동적 마커(`{{post:...}}`) 잔존 — **PO2 런타임 helper 필요** (현재 3,983건) |

## gemini 전용 필드 (러너)

| 필드 | 타입 | 설명 |
|---|---|---|
| `repaired` | boolean | 스팬 분리자 갭 결정적 복구 발생 여부 |
| `l2_retries` | number | L2 구조 문제 힌트 재시도 횟수 (유닛 단위 합계) |
| `api_calls` | number | 유닛 수 + L2 재시도 (배치 모드에서 실제 호출 수와 다를 수 있음) |
| `escalated` | boolean | 승격/2차 시도 사용 여부 (tier 2 개입) |
| `escalated_units` | number | flash 승격된 유닛 수 |
| `tier` | string | `base` (1차만) / `escalated` (승격 사용) |

## 예시

### ko_reuse (마커 없음)

```json
{
  "record_id": "tr_8f2c1a9e3b44_ko",
  "source_text_hash": "8f2c1a9e3b44...",
  "source_text": "You walk into the shop.\n<<npc>> looks at you.\n",
  "translated_text": "상점에 들어선다.\n<<npc>>가 너를 본다.\n",
  "source_path": "overworld-town/loc-test/main.twee",
  "passage_name": "Test Passage",
  "unit_id": "overworld-town/loc-test/main.twee:Test Passage",
  "request_id": "req_ko_reuse",
  "model": "ko_reuse",
  "temperature": null,
  "created_at": "2026-08-08T12:00:00+09:00",
  "placeholder_ok": true,
  "post_status": "none",
  "source": "ko_reuse",
  "level": "passage"
}
```

### gemini (승격 사용)

```json
{
  "record_id": "tr_9d01b2c3a5e6_gemini",
  "source_text_hash": "9d01b2c3a5e6...",
  "source_text": "...",
  "translated_text": "...",
  "source_path": "overworld-plains/loc-farm/work.twee",
  "passage_name": "Farm Work",
  "unit_id": "overworld-plains/loc-farm/work.twee:Farm Work",
  "request_id": "req_20260808_005",
  "model": "gemini-2.5-flash-lite",
  "temperature": 0.7,
  "created_at": "2026-08-08T17:00:00+09:00",
  "placeholder_ok": true,
  "post_status": "runtime_remaining",
  "source": "gemini",
  "level": "passage",
  "repaired": true,
  "l2_retries": 1,
  "api_calls": 102,
  "escalated": true,
  "escalated_units": 23,
  "tier": "escalated"
}
```

## 저널 스키마 (`tmp/journals/req_<id>.jsonl`)

### unit 줄

```json
{
  "kind": "unit",
  "request_id": "req_...",
  "source_path": "...",
  "passage_name": "...",
  "unit_index": 5,
  "unit_count": 100,
  "status": "ok | placeholder_drop | reorder | foreign_token | format_hallucination | prose_drop | malformed_post_marker",
  "escalated": false,
  "model": "gemini-2.5-flash-lite",
  "translated_text": "..."   // ok일 때만
}
```

### passage 줄

```json
{
  "kind": "passage",
  "request_id": "req_...",
  "source_path": "...",
  "passage_name": "...",
  "status": "ok | failed",
  "reason": null | "skeleton_mismatch | ...",
  "record_id": "tr_..._gemini"   // ok일 때만
}
```

## 보는 법

```bash
# 뷰어 (보기 좋게 출력)
uv run python -m translation.store_view --passage "Farm Work"
uv run python -m translation.store_view --last 3
uv run python -m translation.store_view --hash 9d01b2 --full
```
