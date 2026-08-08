# Gemini 풀패시지 번역 러너 구현 피드백 요청

기준일: 2026-08-08
목적: 2순위 구현(`translation/translate_passages.py` + 관련 수정)의 미흡
지점을 리뷰받기 위한 문서. 코드베이스 전체를 몰라도 읽을 수 있게 핵심
코드/흐름을 포함. **"왜 이렇게 오래 걸렸나"에 대한 시간 분석 포함.**

## 1. 이 구현이 하는 일

번역 파이프라인은 passage(게임 장면) 단위로 동작한다. 영어 passage를
유닛(문장 묶음)으로 쪼개 Gemini로 번역하고, 다시 합쳐 게임 구조를
보존한 채 한국어 passage로 만든 뒤, 재사용 스토어(JSONL)에 레코드로
저장한다. 이 레코드는 어셈블러가 `game_ko/` 트리를 만들 때 사용한다.

## 2. 러너 내부 흐름과 검증 계층

```text
translate_passage(path, passage)
  ├─ ① mask_passage       → artifact (보호 스팬 = 매크로/링크/변수)
  ├─ ② chunk_passage      → units
  ├─ ③ 유닛별: translate_unit → post_process
  │      └─ 검증 L1: verify_placeholders (토큰 보존, 재시도 3회 내장)
  ├─ ④ joined 병합
  ├─ ⑤ repair_separator_newlines  ← 이번에 추가한 결정적 복구
  ├─ ⑥ restore_joined     → 복원된 번역 body
  └─ ⑦ 검증 L3: _skeleton_ok (보호 스팬 시그니처 비교)
        → 통과 시 passage 레코드 저장 (source=gemini, level=passage)
```

검증 계층: L1(유닛 토큰) → 복구 → L3(패시지 구조). L2(유닛 구조)는
없다 — 이게 아래 H3과 연결된다.

## 3. 핵심 인터페이스

```python
# translation/translate_passages.py
translate_passage(path, passage, *, request_id, store_records, force=False,
                  game_root=None) -> tuple[dict | None, str]
    # (레코드, 사유): 사유 = "ok" | "skipped" | "placeholder_drop"
    #                 | "restore_failed" | "skeleton_mismatch"

verify_separator_newlines(artifact, joined) -> list[str]
    # 보호 스팬 사이의 공백 분리자가 번역에서 드롭된 placeholder 목록
repair_separator_newlines(artifact, joined) -> str
    # 드롭된 분리자를 원본(masked) 기준으로 재삽입 (결정적)
restore_joined(artifact, joined) -> bytes
_skeleton_ok(source_artifact, translated_body, passage_name, source_path) -> bool
    # 번역 body를 마스킹해 보호 스팬 시그니처가 원본과 같은지 비교
next_request_id(records) -> str          # req_<yyyymmdd>_<seq> (KST)
_rel_source_path(path, game_root) -> str # game-root 상대경로로 정규화
```

레코드는 기존 ko_reuse 스키마와 동일하며 `source="gemini"`, `model`,
`temperature`, `created_at`(KST)이 채워진다. `source_path`는 **game-root
상대경로**(`overworld-town/...`) — ko_reuse와 동일 규약 (H6).

## 4. 왜 이렇게 오래 걸렸나 (시간 분석)

시계열 (각 라운드 ≈ 25~30초 번역 + 30~90초 추적 스크립트):

| # | 발견한 실패 | 원인 | 대응 | 비용 |
|---|---|---|---|---|
| 1 | versionInfo 실패 | **[widget] 코드 passage를 번역함** | 코드 passage 거절 추가 | 1라운드 |
| 2 | versionInfo: 끝부분 개행 드롭 | 모델이 매크로 사이 개행 삭제 | (과잉) 유닛 개행 카운트 검증 추가 | 1라운드 |
| 3 | Ocean Breeze: 유닛 22개 전부 개행 -1~3 | 검증이 과격함 (모든 유닛 위반) | 개행 검증 **제거** | 1라운드 |
| 4 | Ocean Breeze: 스팬 18개 병합 | 모델이 **분리자 개행** 드롭 | 재시도 루프 추가 → **무효** (모델 반복 위반) | 2라운드 |
| 5 | 병합 잔존 | 분리자가 **개행이 아니라 공백**인 케이스 | `\n` 전용 → 공백 전체로 일반화 | 1라운드 |
| 6 | `$var를` 스팬 변형 | **파서가 한글 조사를 변수명에 흡수** (`isalnum()`) | 파서 ASCII 전용 수정 | 2라운드 |
| 7 | passage-list에서 누락 | **gemini 레코드 source_path에 `game/` 접두어** | game-root 상대경로 정규화 + 낡은 레코드 정리 | 2라운드 |

**근본 원인 3가지:**

1. **실패 사유가 불투명했다 (최대 비용)**. `translate_passage`가 처음엔
   `None`만 반환해, 실패할 때마다 "어느 단계에서 실패했는지" 파이프라인을
   수동 재현하는 스크립트를 5~6번 짜야 했다. `(record, reason)` 반환은
   **구현 첫 버전부터 있어야 할 설계**였다 — 사유 문자열 하나가 디버깅
   라운드를 라운드당 30~90초 → 즉시로 줄였을 것.
2. **모델 동작 가정이 틀렸다**. "구조 위반도 재시도로 고쳐질 것"이라는
   가정 — 실제로는 분리자 드롭을 모델이 반복 위반해 재시도가 전부
   무효였다. "재시도로 잡히는 실패(토큰 드롭) vs 결정적으로 복구 가능한
   실패(구조)"를 처음부터 구분했어야 했다.
3. **파서가 "KO body를 파싱한다"는 전제가 없었다**. `_consume_variable`의
   `isalnum()` 버그는 한국어 텍스트가 파서에 들어오면서 처음 발현했다.
   등록 단계(`register_ko_reuse._verify_passage`)도 같은 파서를 쓰지만
   3-match KO body는 변수 뒤 조사 대신 `【 】`마커를 써서 버그가 숨어
   있었다. **KO body 파싱 픽스처 부재**가 근본 원인.

총 디버깅 라운드 ≈ 10회, 그중 재시도(라운드 4)와 과잉 검증(라운드 2~3)이
~4라운드의 순수 낭비. 수정 3건의 절반(파서/경로)은 러너 밖의 잠재 버그였다.

## 5. 미흡 지점 (우선순위순)

### H1. 실패 사유 부재 → **이미 수정됨** (교훈으로 기록)

```python
# 수정 전: 실패 지점을 알 수 없어 매번 수동 추적 필요
def translate_passage(...) -> dict | None:   # None = 실패 (왜? 모름)
# 수정 후:
def translate_passage(...) -> tuple[dict | None, str]:
    # "placeholder_drop" | "restore_failed" | "skeleton_mismatch" ...
```

- 교훈: 다단계 검증 파이프라인은 **첫 버전부터 실패 사유를 반환**해야 한다.
  유닛/복구/패시지 3계층의 어느 곳에서 실패했는지가 곧 디버깅 경로다.

### H2. 실패 덤프 부재 (디버깅 재현성)

- LLM 출력이 **비결정적**이라 같은 코드·입력으로 수동 추적(통과)과 러너
  실행(실패)이 갈렸다. 실패 시 "어떤 유닛에서 어떤 출력이 나왔는지"가
  남지 않아 원인 재현에 매번 재번역이 필요했다.
- 제안: `--debug-dir` 옵션 — 실패한 passage의 유닛별 masked/translated
  텍스트 + 실패 사유를 JSONL로 덤프. 재번역 없이 원인 분석 가능.

### H3. 검증 계층의 비대칭 (L1/L3는 있으나 L2 부재)

```python
# L1: 유닛 단위 — placeholder 토큰 보존만 검사 (재시도 내장)
# (L2 없음 — 유닛 구조는 검사하지 않음)
# L3: 패시지 단위 — 시그니처 비교 (실패 = 패시지 전체 폐기)
```

- 유닛 구조 문제(분리자 드롭)는 L1에서 안 걸리고 L3에서 패시지 전체를
  폐기시켰다. L3 실패가 "모델이 22유닛을 다 번역한 뒤" 발생하므로
  유닛 1개 때문에 25초치 작업이 버려졌다.
- 제안: L2로 "유닛 내부에서 보호 스팬이 인접하게 병합됐는지" 조기 검사
  (실패한 유닛만 재번역/복구) — L3 실패 비용 절감.

### H4. 재시도 vs 복구 전략의 명시적 분리 필요

- 이번 경험: placeholder 드롭 = 재시도로 해결 가능. 분리자 드롭 = 모델이
  반복 위반 → 재시도 무효, 결정적 복구(`repair_separator_newlines`)가 정답.
- 제안: 실패 타입별 전략 테이블을 문서화하고 러너에 반영:
  `token drop → retry`, `separator drop → repair`, `signature mismatch →
  reprocess (재번역 후에도 실패 시 덤프)`.

### H5. 분리자 정의의 일반화 지연

```python
# 1차: m_after == "\n"만 검사  → 공백 분리 케이스 누락 (라운드 5 낭비)
# 2차: m_sep.isspace() 전체   → 정답이었음
```

- "분리자"를 처음부터 "공백(개행 포함)"으로 정의했으면 한 라운드 절약.
  교훈: 구조 유지 검사는 "어떤 문자가 스팬을 분리하는가"의 **완전 집합**을
  먼저 정의하고 구현.

### H6. 레코드 경로 규약이 코드에만 존재

- `source_path`는 game-root 상대경로여야 한다는 규약이 ko_reuse(등록
  스크립트)와 gemini(러너)에 중복 구현됐고, 처음엔 `game/` 접두어가
  붙어 어셈블러 키 불일치를 만들었다 (라운드 7).
- 제안: 스토어 스키마 문서(`translation-reuse-design.md`)에
  "`source_path`는 game-root 기준 상대경로" 명시 + `_rel_source_path`를
  등록/러너 공용 유틸로 승격.

### H7. KO body 파싱 픽스처 부재 (파서 잠재 버그)

- `_consume_variable`의 `isalnum()`이 한글을 변수명에 흡수 — KO corpus가
  파서에 들어온 이번에 처음 발현. 영어 corpus 검증(baseline matched)은
  이 계열 버그를 못 잡는다.
- 제안: 파서 테스트에 **KO 스니펫 픽스처** 추가 (예:
  `$worn.upper.name를`, `<<he "로빈">>가` 등) — "변수 뒤 조사 부착"이
  실제 게임에서 흔한 패턴이므로.

### H8. 검증 루프의 조기 단계 부재

- 디버깅 중 매 라운드에 25~30초 번역 + 수동 추적 + (때로) verify.py
  전체(2분)를 돌렸다. 러너 산출물(레코드)이 어셈블러에 흘렀는지는
  스토어 → `pick_passage_records` → `_process_file` 함수 호출로
  **30초 내 조기 검증** 가능했다.
- 제안: "레코드 → 어셈블 함수 호출 → 시그니처 검증" 스모크 단위 테스트를
  러너 테스트에 포함 (풀 빌드 없이 흐름 검증).

## 6. 리뷰어에게 받고 싶은 질문

1. H3의 L2(유닛 구조 조기 검사)를 도입할 가치가 있는가? L3 폐기 비용
   (유닛 수 × ~1초)가 커지는 전투 passage(561유닛)에서 특히.
2. 실패 시 **자동 재번역 vs 덤프 후 수동 판단** 중 어느 쪽이 맞는가?
   (H2/H4 — 코스트 관점)
3. `repair_separator_newlines`의 결정적 복구가 "번역 품질을 조작"한다는
   우려는 타당한가? (원본 구조와 동일해지는 방향이므로 안전하다고
   판단했지만, 리뷰 필요)
4. 파서의 ASCII 전용 변수명 수정이 장기적으로 안전한가? (SugarCube
   스펙 일치 + corpus 영향 0 실측했지만, 향후 비-ASCII 변수 등장 시)

## 7. 재현 방법

```bash
# 유닛 테스트 (164개)
uv run python -m unittest discover -s tests

# 러너: passage 1개 번역 → 스토어에 레코드 저장
uv run python -m translation.translate_passages \
  --file game/overworld-town/loc-cafe/main.twee --passage-name "Ocean Breeze"

# 전체 체인 검증 (~2분)
python3 build/verify.py
```

## 9. 리뷰 반영 이력 (2026-08-08)

| 항목 | 리뷰 지적 | 판정 | 반영 |
|---|---|---|---|
| Q1 L2 도입 | 관측 없이 만들지 말 것 — skeleton 사유 세분화 먼저 | **동의 (보류)** | 미구현 — H2 덤프로 관측 후 결정 |
| Q2 자동 재번역 | 구조 위반은 재시도 무효 — 덤프 후 수동 | **동의** | 재시도 루프 만들지 않음 (기존 유지) |
| Q3 repair 품질 조작 | 아님, 단 `repaired` 플래그 권장 | **동의** | 레코드에 `repaired: bool` 추가 (실측 True) |
| Q4 ASCII 파서 fix | 안전 (SugarCube 스펙) | **동의** | 무변경 |
| 🟡 repair 갭 1글자 뭉갬 | `\n\n`→`\n` 문단 구분 소실 — 전체 갭 복원 필요 | **버그 확정** | `_separator_gap`/`_leading_whitespace`로 전체 갭 비교·복원. `verify`도 갭 축소 감지로 강화. 테스트 추가 |
| 🟡 배치 예외 크래시 | `translate_passage` 예외 시 전체 중단 | **버그 확정** | per-passage try/except → `stats["failed"]`에 `exception: ...` 기록 후 계속 |
| 새 이슈 1 post 마커 미검증 | `{{post:...}}` 오타가 검증 사각지대 | **타당** | `verify_malformed_post_markers` (닫힘 누락/단일 `}`) — 실패 사유 `malformed_post_marker`, 테스트 추가 |
| 새 이슈 2 `_get_model` 캐싱 | 다중 모델 시 무시됨 | **인지만** | 무변경 (문서에 기록) |
| 새 이슈 3 API 재시도 부재 | 429/500/timeout propagate → 배치 크래시 | **버그 확정** | `_generate`에 API 레벨 재시도 3회 + backoff (콘텐츠 재시도와 분리) |
| 새 이슈 4 restore 중복 | `restore_translated`/`restore_joined` 로직 이원화 | **타당** | `restore_joined`를 client.py로 승격, `restore_translated`가 위임 |
| 사소 `_rel_source_path` | game_root 밖 경로 조용히 원본 반환 (라운드 7 재발 위험) | **타당** | `logging.warning` 추가 |
| 정정 | `verify_placeholders` 반환값 역전 — 버그 아님 | **확인됨** | 무변경 (list[str] 의미, 문서 §3에 시그니처 명시됨) |

미반영(후순위): L2, 자동 재번역 루프, `_get_model` 캐시 개선, H3.

## 8. 이번에 잡은 버그 3건 (로그)

1. **[widget] 코드 passage 번역** — 어셈블러가 제외하는 정책과 불일치.
   러너가 코드 passage를 거절하도록 수정 (`_pick_passage`).
2. **파서 한글 흡수** — `_consume_variable` `isalnum()`이 `$var를`에서
   `를`을 변수명에 포함 → ASCII 전용(`_ascii_name_char`)으로 수정.
   corpus 영향 0 (baseline matched). SugarCube 변수명은 ASCII 전용.
3. **레코드 경로 불일치** — gemini 레코드가 `game/` 접두어로 저장 →
   ko_reuse 키와 어긋나 어셈블에서 누락. `--game-root` 상대경로 정규화.
