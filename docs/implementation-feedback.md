# 번역 빌드 체인 구현 피드백 요청

기준일: 2026-08-08
목적: 이번 세션에서 구현한 "번역 결과물 → 게임 빌드 → 브라우저 스모크" 체인의
미흡 지점을 리뷰받기 위한 문서. **코드베이스 전체를 몰라도** 읽을 수 있게
핵심 코드/인터페이스/호출 흐름을 문서 안에 포함했다.

## 1. 이 체인이 하는 일 (맥락 3줄)

이 프로젝트는 영어 게임(Degrees of Lewdity Plus)의 텍스트를 한국어로 번역하는
파이프라인이다. 기존 KO 번역본(3-match 데이터)과 신규 LLM 번역을 **passage
단위 레코드(JSONL)**로 모아, 원본 게임 트리와 합쳐 **`game_ko/`** 트리를
만들고, Tweego로 컴파일해 실제 플레이 가능한 **HTML 빌드**를 산출한다.
마지막으로 headless Chromium에서 그 빌드를 열어 "번역이 실제로 잘 들어갔고
게임이 안 깨지는지"를 자동 검증한다.

## 2. 데이터 흐름과 호출 체인

```text
research/golden/corpus-triple-match.jsonl (3-match KO 본문)
        │  translation/register_ko_reuse.py  [등록, 1회성]
        ▼
work/translations/ko-reuse.jsonl ── passage 단위 레코드 3,151건
        │  translation/assemble_game_ko.py   [어셈블, ~6분]
        ▼
game_ko/  ── game/ 전체 복사 + 번역 passage body 스플라이스
        │  build/dol_build.py compile        [컴파일, ~2초]
        ▼
build/dol-plus-ko.html
        │  browser_smoke.py run --passage-list [스모크, ~6초]
        ▼
build/browser-smoke/report.json ── checks + passageList + 에러 목록
```

모듈 간 계약은 오직 **JSONL 레코드 스키마**(§3.1)와 함수 인터페이스(§3.2)
뿐이다. 파일/경로는 문서 §6의 커맨드로 재현 가능.

## 3. 핵심 인터페이스

### 3.1 레코드 스키마 (`translation/register_ko_reuse.py` `make_record`, 1줄 = 1 passage)

```json
{
  "record_id": "tr_<source hash 12자>_ko",
  "source_text_hash": "<sha256(source_text)>",
  "source_text": "<원본 passage body 텍스트>",
  "translated_text": "<KO body 텍스트, 【 】마커는 {{post:...}}로 정규화됨>",
  "source_path": "overworld-town/loc-hospital/abduction.twee",
  "passage_name": "Abduction Hospital Corridor Wolves",
  "unit_id": "<source_path>:<passage_name>",
  "request_id": "req_ko_reuse | req_<yyyymmdd>_<seq>",
  "model": "ko_reuse | gemini-2.5-flash-lite",
  "temperature": null,
  "created_at": "<ISO 8601 KST 타임스탬프, Asia/Seoul>",
  "placeholder_ok": true,
  "post_status": "static_done | none",
  "source": "ko_reuse | gemini",
  "level": "passage"
}
```

주의: `translated_text`의 leading/trailing 개행 구조는 `source_text`와
동일하게 정규화되어 저장된다 (`register_ko_reuse.match_boundaries`).

### 3.2 모듈 함수 인터페이스

```python
# translation/store.py
load_translations(path) -> dict[hash, list[record]]      # hash 그룹, append 순
find_reuse(hash, records) -> record | None               # 최신 유효 레코드
find_passage_reuse(body_text, records, min_level="passage") -> record | None
append_record(record, path)                              # JSONL append
passage_placeholder_signature(artifact) -> list[str]     # 보호 스팬 원본 bytes
ko_body_preserves_skeleton(ko_body, signature) -> bool   # 순서 보존 검사

# translation/assemble_game_ko.py
pick_passage_records(store_path) -> ({(path, name): record}, skipped_stats)
assemble(records, game_root, output_root, *, verify=True, known_names=None) -> stats
macro_sequence(text: bytes) -> list[str]                 # 구조 핑거프린트
_verify_assembled(path, spliced_names, known_names, *, original=None) -> [codes]

# translation/register_ko_reuse.py
register_ko_reuse(triple_match_path, out_path, *, report_path=None) -> stats
_verify_passage(row) -> str | None                       # 등록 시 구조 대칭 검사
```

### 3.3 passage body span 모델 (파서 기준)

파서(`pretranslation_cst/parser.py`)가 각 passage에 대해 파일 내 byte span을
기록한다. **body span은 헤더(`:: Name [tags]`) 직후부터 다음 헤더 직전까지며,
leading/trailing 개행을 포함한다.**

```python
# 예: ":: Two\n\nSecond passage here.\n\n" 파일에서
passage.body_span  # Span(start=29, end=52) → body 텍스트 = "\nSecond passage here.\n\n"
```

## 4. 미흡하다고 생각되는 부분 (우선순위순)

각 항목은 [위치 → 코드 → 문제 → 제안] 형식. **상태: 2026-08-08 리뷰 반영 완료**
(확정 버그 2건 + H1/H2/H3/H4/H6/H7 수정, 실측: 어셈블 5:50 → 1:49).

### H1. 어셈블이 느리다 — 병렬화/캐싱 없음 → **수정 완료**

```python
# translation/assemble_game_ko.py assemble() — 파일 단위 순차 루프
for rel in sorted(by_file):                    # 343개 파일
    data = src.read_bytes()
    source = parse_file(data, rel, ...)        # ① 스플라이스용 파싱
    ...
    if verify:
        problems = _verify_assembled(dst, spliced_names, known_names,
                                     original=src.read_bytes())
        # ② _verify_assembled가 원본을 다시 parse_file(원본 재파싱)
        # ③ 그리고 결과물도 다시 parse_file(결과물 재파싱)
```

- 파일당 파싱 3회 반복. `corpus_verify`는 ProcessPoolExecutor(16 워커)를
  쓰는데 어셈블러는 단일 스레드 (실측: splice 348s + verify 232s).
- **수정**: ① 원본 파싱 결과(`SourceFile`)를 verify에 재사용 (3→2회),
  ② 파일 단위 `ProcessPoolExecutor` 병렬화. 실측 5:50 → **1:49 (3.2배)**.
  `--workers` 옵션 제공.

### H2. verify의 구조 검증이 "매크로 토큰 시퀀스" 휴리스틱이다

```python
# translation/assemble_game_ko.py — 검증의 전부
_SEQ_RE = re.compile(r"<<\s*/?\s*[A-Za-z_]\w*|\[\[|]]|</?[a-z][^>]*>")

def macro_sequence(text: bytes) -> list[str]:
    return _SEQ_RE.findall(text.decode("utf-8", errors="replace"))
# 비교: macro_sequence(원본 body) != macro_sequence(스플라이스 결과 body)
#     → "macro_sequence_mismatch"
```

- 매크로 **이름/링크/태그 토큰의 순서**만 비교한다. 중첩 균형, 인자 구조,
  실제 보호 스팬의 원본 bytes는 비교하지 않는다 (같은 이름 매크로의
  재배치/중첩 변경은 감지 불가).
- 반면 **등록 단계**에는 더 강한 검사가 이미 있다:

```python
# translation/register_ko_reuse.py _verify_passage()
src_sig = passage_placeholder_signature(mask_passage(src_synthetic, src_passage))
ko_sig  = passage_placeholder_signature(mask_passage(ko_synthetic, ko_passage))
if src_sig != ko_sig:          # 보호 스팬 원본 bytes 시퀀스의 대칭 비교
    return "skeleton_mismatch"
```

- **수정**: 어셈블 verify에 시그니처(보호 스팬 원본 bytes) 비교 추가
  (`_verify_assembled` — `skeleton_mismatch`/`mask_failed` 코드).
  매크로 시퀀스 비교는 유지 (2중 방어). 실측: 3,151건 재검증 0건 불일치.
- **수정**: `ko_body_preserves_skeleton(ko_body, ko_sig)` 2차 체크 제거 —
  `ko_sig`가 ko_body 자기 자신에서 파생되어 항상 참인 방어막이었음
  (리뷰 지적, 코드 검증 완료).

### H3. 어셈블이 비원자적이다 (실패 시 부분 출력 위험) → **수정 완료**

```python
# assemble() 시작
output_root.mkdir(parents=True, exist_ok=True)
shutil.copytree(game_root, output_root, dirs_exist_ok=True, symlinks=False)
# ... 그 후 343개 파일을 순차 스플라이스하며 game_ko/에 직접 덮어씀
```

- 6분짜리 실행이 중간에 죽으면 절반만 번역된 트리가 남는다. 재실행 시
  `dirs_exist_ok=True`가 낡은 파일을 남길 수 있다.
- **수정**: staging 디렉터리(`.{name}.tmp-<pid>`)에 어셈블 후
  `replace()` 원자 스왑 + 이전 트리 백업 복원. 재실행 시 낡은 파일 제거
  (테스트 `test_stale_output_files_removed` 추가).

### H4. 스모크의 "번역 검증" 기본값이 비어 있다 → **부분 수정**

```mjs
// browser_smoke.mjs — 옵션 오버레이 한국어 확인
const expectedOptionsTexts = args["expect-options-text"] ?? [];
checks.koreanOptionsApplied =
  expectedOptionsTexts.length === 0 ||          // ← 기본: 빈 배열 → 항상 true
  expectedOptionsTexts.every((text) => optionsText.includes(text));
```

- `--expect-options-text`를 안 주면 **옵션 UI가 영어로 회귀해도 잡히지 않는다.**
- **수정**: skip 시 `report.warnings.optionsCheckSkipped: true` 기록 —
  침묵 성공이 리포트에서 보이도록. (한국어 포함 비율 지표는 미구현 — 후순위)
- **수정**: 반복 옵션(`--expect-options-text`)을 **항상 배열로 정규화** —
  단일 전달 시 문자열이 되어 `.every()` TypeError로 죽던 버그 해결
  (리뷰 지적, 실측 검증: 단일 옵션 실행 정상).
- passage-list TSV도 수동 생성 중 (레코드에서 한국어 조각 추출):

```python
# /tmp/opencode/translated-passages.tsv 생성 (수동, 문서화 안 됨)
ko = re.compile(r'[가-힣]{4,}')
lines = [name + '\t' + (ko.search(rec['translated_text']).group(0)
                        if ko.search(rec['translated_text']) else '')
         for (path, name), rec in sorted(records.items())]
```

- 제안: 기본 기대 문자열 파생 또는 "스토리 passage 중 한국어 포함 비율 ≥ N%"
  지표 추가. TSV 생성은 어셈블러(또는 별도 스크립트)에 포함.

### H5. 스모크 셀렉터가 게임 UI 구조에 강하게 결합

```mjs
// browser_smoke.mjs — 하드코딩된 셀렉터
page.locator("#ui-dialog-body")                 // age gate 다이얼로그
page.locator("#startCaption")                   // 시작 화면 버튼 영역
page.locator("#customOverlay")                  // 옵션/세이브 오버레이
page.locator(".customOverlayClose")
// 버튼 이름은 영어/KO try-both 정규식 (getByRole name: /^(OPTIONS|옵션)$/ 등)
```

- 게임 UI 구조가 바뀌면 스모크가 무의미하게 실패한다 (셀렉터 = 게임 버전
  스냅샷). 현재는 try-both 정규식으로 언어만 완화된 상태.
- 제안: 셀렉터 설정 파일 분리, 또는 "요소 없음 = 경고(비차단)" 정책.

### H6. 테스트 커버리지 갭 → **부분 수정**

`tests/test_assemble_game_ko.py` — 기존 5건 + 추가 2건 (총 7건):
단일 스플라이스, 드리프트 skip, 레코드 최신 선택, 경계 newline 보존,
결과물 파싱, **멀티 passage 역순 스플라이스**, **낡은 산출물 제거(원자성)**.

- **멀티 passage 파일(역순 스플라이스 경로)** 픽스처 추가 — 이 경로에서
  실제로 경계 newline 버그가 났는데 회귀 테스트로 고정됨 (리뷰 지적,
  "버그를 잡았다는 건 재현 케이스가 이미 손에 있다" 반영).
- **코드 passage([widget] 태그) 제외** 테스트 없음 — 미수정 (후순위).
- **같은 passage 이름의 중복 레코드** 테스트 없음 — 미수정 (후순위).
- `browser_smoke.mjs`는 유닛 테스트가 전혀 없음 — E2E 성격이라 스모크
  자체가 역할을 대신한다는 리뷰 의견에 동의, 미수정.

### H7. 레코드 데이터의 일관성 문제를 어셈블러가 떠안고 있다 → **부분 수정**

```python
# assemble() 스플라이스 시 경계 보정 (3-match KO body가 trailing 개행을 버리는 형식)
leading  = original_body[: len(original_body) - len(original_body.lstrip(b"\n"))]
trailing = original_body[len(original_body.rstrip(b"\n")):]
new_body = leading + translated.strip("\n").encode("utf-8") + trailing
```

- 원인은 등록 데이터(`corpus-triple-match.jsonl`의 `ko_body`)가 body 경계
  개행을 포함하지 않는 형식인데, 소비자(어셈블러)가 보정하는 구조.
- **수정**: 등록 단계에서 `register_ko_reuse.match_boundaries()`로 KO body를
  원본 body와 같은 개행 구조로 정규화해 저장. 어셈블러의 보정은 안전망으로
  유지 (다른 소스의 레코드 대비).
- **수정**: 등록 skip 레코드(`skeleton_mismatch` 18건)를 `skipped_records`
  목록(경로/이름/사유)으로 보고 — 조용한 누락 방지.
- 낡은 레코드(현재 버전에 없는 passage, 1건: `Widgets Office Lift`)는
  어셈블러에서 `passage_not_found`로 보고 — 미수정 (후순위, ID 보고).

### H8. 오케스트레이션 부재

- 어셈블 → 컴파일 → 스모크가 3개 커맨드(§6)로 분리. "한 번에 검증"하는
  진입점이 없어서 단계 누락/스테일 산출물 혼동 여지가 있다.
- 제안: `python3 build/verify.py` 또는 Makefile — 어셈블(변경 감지 시) →
  컴파일 → 스모크 + 레포트 집계를 하나로.

## 5. 리뷰어에게 받고 싶은 질문 (관련 코드 위치 포함)

1. **어셈블 검증 정책**: 등록 시점의 강한 검사(`_verify_passage`,
   `register_ko_reuse.py:90`)만으로 충분한가, 아니면 어셈블 시점에도
   보호 스팬 비교(H2 제안)가 필요한가? H1 성능과의 트레이드오프.
   → **리뷰 답변**: 어셈블 시점 검사 유지 필요 (트리 갱신 시 등록 검증이
   무의미해질 수 있음). **반영: 시그니처 비교 추가 + 병렬화로 비용 상쇄.**
2. **스플라이스 방식**: 원본 트리 복사 + body byte span 교체
   (`assemble_game_ko.py:139-145`)가 유지보수 관점에서 타당한가?
   대안(파일 전체 재생성, diff 패치)이 있는가? H3 원자성과 함께 판단.
   → **리뷰 답변**: lossless CST 원칙과 일관, 방식 유지 권장. **반영:
   방식 유지 + 원자성(H3) 보강.**
3. **스모크 검증 목표**: "번역분 검증"과 "게임 회귀 검증" 중 어느 쪽이
   주 목적인가? 현재는 UI 7종(`browser_smoke.mjs` checks) + passage-list
   전수(textMatch)인데, H4/H5의 강도/유연성 결정에 기준이 필요.
   → **리뷰 답변**: 분리보다 report.json에서 카테고리 명시 구분 권장.
   **미반영 (후순위)** — 실패 시 "번역/UI 어느 쪽 문제인지" 구분 필드.
4. **성능**: 6분(파일당 파싱 3회)이 실사용에 문제인가? 병렬화 vs 검증
   축소 중 어디에 투자할 가치가 있는가?
   → **리뷰 답변**: 병렬화 먼저 + verify 강화 권장. **반영: 병렬화 +
   verify 강화, 실측 1:49.**
5. **레코드 스토어의 level 혼재**: passage/unit 레코드가 한 JSONL에
   섞인다 (`store.py find_passage_reuse`가 `level`로 필터). 장기적으로
   통일/분리 어느 쪽? (설계 문서: `docs/translation-reuse-design.md`)
   → **미판정 (후순위).**

## 6. 재현 방법

```bash
# 어셈블 (3,151건, ~6분) — game_ko/ 생성
uv run python -m translation.assemble_game_ko

# 컴파일 (~2초, 첫 실행은 툴체인 다운로드 ~14초)
python3 build/dol_build.py compile --force

# 스모크 (~6초) — passage-list는 'passage<TAB>기대문구' TSV
python3 browser_smoke.py run --html build/dol-plus-ko.html \
  --output build/browser-smoke --passage-list /tmp/opencode/translated-passages.tsv

# 유닛 테스트 (154개)
uv run python -m unittest discover -s tests

# EN 원본 대비 A/B (회귀 원인 분리용)
cp -r game /tmp/opencode/game_en
python3 build/dol_build.py compile --source /tmp/opencode/game_en --output build/dol-en.html --force
python3 browser_smoke.py run --html build/dol-en.html --output /tmp/opencode/smoke-en
```

산출물: `build/browser-smoke/report.json` (checks + passageList + 에러 목록),
`build/dol-plus-ko.html.build.json` (컴파일 보고).

## 7. 이번 구현에서 실제로 잡았던 버그 (회귀 경험 공유)

1. **KO body trailing 개행 누락 → 다음 passage 헤더가 body에 흡수됨**
   (스모크에서 위젯 실행 에러로 발견) — 경계 공백 보존으로 해결.
2. **[widget] 태그 passage(46건)가 번역 대상에 포함 → 위젯 코드가 번역돼
   런타임 에러** (`schooleffects` 등 "macro does not exist") — 코드 passage
   제외로 해결.
3. **매크로 구조 검사의 false positive** — `<<link [[Next|X]]>>`의 라벨
   번역을 구조 변경으로 오인 → 매크로 이름/링크/태그만 비교로 정규화.

## 8. 리뷰 반영 이력 (2026-08-08)

| 항목 | 리뷰 지적 | 반영 |
|---|---|---|
| 확정 버그 1 | `parseArgs`: 반복 옵션 1개 전달 시 문자열 → `.every()` TypeError | 수정 — `MULTI_OPTIONS` 항상 배열화, 실측 검증 |
| 확정 버그 2 | `created_at` 하드코딩 `"2026-08-08"` | 수정 — `datetime.now(UTC)` ISO |
| 🟡 | `ko_body_preserves_skeleton(ko_body, ko_sig)` 항상 참 | 제거 — 자기 파생 시그니처 자체 검사 |
| H6 | 멀티 passage 역순 스플라이스 테스트 부재 | 추가 — `test_multi_passage_same_file_reverse_splice` |
| 문서 | §3.1 스키마에 unit_id/request_id/model/temperature/created_at 누락 | 보완 |
| H3 | 비원자적 쓰기 (조용한 실패 패턴) | staging + 원자 스왑 + 백업 복원 |
| H1/H2 | 파싱 재사용 + 병렬화, verify는 강화 유지 | 원본 파싱 재사용(3→2), ProcessPoolExecutor, 시그니처 비교 추가 — 실측 5:50→1:49 |
| H4 | 빈 기대 문자열 침묵 성공 | `warnings.optionsCheckSkipped` 기록 |
| H7 | 경계 개행 보정을 소비자가 부담 | 등록 시 `match_boundaries()` 정규화 + `skipped_records` ID 보고 |

미반영(후순위): H4 한국어 비율 지표, H5 셀렉터 분리, H8 오케스트레이션,
Q3 체크 카테고리 분리, Q5 level 통일.
