# 테스트 소요 시간 분석과 경량화 방안

기준일: 2026-08-07

## 현황

```text
$ time python3 -m unittest discover -s tests
Ran 112 tests in 4.832s
real 0m4.962s
```

테스트 4.96s 중 4.81s(97%)가 `tests/test_macro_audit.py` 2개 테스트에서
발생한다.

## 모듈별 측정

| 모듈 | 테스트 수 | 소요 | 비고 |
|---|---:|---:|---|
| test_macro_audit | 34 | 4.81s | 병목 |
| test_verify | 19 | 0.20s | |
| test_pretranslation_cst | 22 | 0.13s | |
| test_square_markup | 37 | 0.11s | |
| **합계** | **112** | **~5.0s** | |

`test_macro_audit` 내에서도 2개 테스트가 전체의 99%를 차지한다.

| 테스트 | 소요 | 원인 |
|---|---:|---|
| `test_audit_report_is_deterministic` | 3.65s | `extract_game_specs` 2회 호출 |
| `test_repo_manifest_passes_audit` | 2.66s | `extract_game_specs` 1회 호출 |
| 나머지 32개 | < 0.07s | 인메모리 fixture |

병목의 99%는 `extract_game_specs` → `extract_js_calls`의 반복 실행이다.

## 병목 원인

`extract_js_calls`(`pretranslation_cst/macro_audit.py:463`)은 game
`**/*.js` 231개 파일 / 4.7MB를 한 글자씩 순회하며 `Macro.add`,
`DefineMacro`, `Macro.delete` 호출을 찾는다.

cProfile 결과(테스트 1회 실행, 14.73s 누적 — cProfile 오버헤드 포함):

| 함수 | 호출 수 | tot time | 비고 |
|---|---:|---:|---|
| `extract_js_calls` | 1,210 | 6.13s | JS 전체 문자 순회 |
| `_extract_js_call` | 9,479,557 | — | 글자마다 호출 |
| `re.Pattern.match` | 9,485,483 | 2.63s | `_CALL_RE.match` |
| `str.isalpha` | 16,993,213 | 2.02s | 글자 분류 |

문제:

1. `extract_game_specs`가 3회 호출됨(deterministic 2회 + repo 1회). 매번
   동일한 4.7MB JS를 처음부터 파싱한다.
2. `extract_js_calls`가 모든 문자에 대해 `_extract_js_call` → `re.match`를
   호출한다. 알파벳/`_`/`$` 문자마다 정규식 매칭을 시도한다.
3. 게임 JS 중 매크로 정의가 없는 대형 파일(clothing-rings.js 260KB 등)도
   전체를 스캔한다.

## 경량화 방안

우선순위 순. 각 방안은 round-trip/audit 검증 결과를 유지하는前提下로 평가한다.

### A. `extract_game_specs` 결과 캐싱 (효과: ~3x, 위험: 낮)

`extract_game_specs`는 순수 함수고 game 디렉터리가 테스트 중 변하지 않는다.
`lru_cache` 또는 모듈 수준 캐시를 두어 동일 경로에 대한 재호출을 1회로 줄인다.

- `test_audit_report_is_deterministic`이 동일 `extract_game_specs`를 2회
  호출하므로 캐시 적중으로 1회 분(2.5s) 절감.
- `test_repo_manifest_passes_audit`도 같은 경로를 쓰므로 두 테스트 합산
  3회 → 1회로 줄어든다. 예상 소요: 4.96s → ~2.6s.
- 구현 위치: `extract_game_specs`에 `functools.lru_cache` 적용, 또는 테스트
  `setUpClass`에서 1회 추출해 `game_specs_override`로 전달.
- 주의: `lru_cache`는 인자(경로)가 해시 가능해야 한다. `Path`는 해시
  가능하므로 문제없음. 단, 캐시가 프로세스 간 격리되므로 CLI/audit 명령에는
  영향 없음.

### B. `_CALL_RE` 사전 필터 (효과: ~2x, 위험: 낮)

`extract_js_calls`가 모든 알파벳 위치에서 `_CALL_RE.match`를 시도한다.
`Macro.add`/`DefineMacro`/`Macro.delete`의 접두어만 빠르게 검사해 매칭
후보 위치를 좁힌다.

- `_CALL_RE.match` 호출 950만 → 예상 수십만 회로 감소.
- 구현: `text.find("Macro.add", pos)` / `text.find("DefineMacro", pos)`로
  후보 위치만 잡고, 그 위치에서 `_CALL_RE.match`를 수행.
- 주의: `_skip_literal`(문자열/주석/regex)이 후보 위치가 문자열 안인지
  판별해야 한다. 기존 `_skip_literal`을 재사용하면 안전.

### C. 대형 비정의 파일 스킵 (효과: ~1.5x, 위험: 중)

매크로 정의가 없는 파일(clothing-*.js, canvasmodel-*.js 등)은
`Macro.add`/`DefineMacro` 문자열이 없으면 `extract_js_calls`을 건너뛴다.

- 파일을 읽기 전 `b"Macro.add"`, `b"DefineMacro"`, `b"Macro.delete"`가
  있는지 바이트 단위로 검사.
- 231개 중 매크로 정의가 있는 파일은 소수(예: `macros/*.js`,
  `base.js`, `ui-*.js`). 나머지 대다수는 스킵.
- 위험: 바이트 검사가 인코딩/주석 안의 문자열에 위양성을 일으킬 수 있으나,
  어차피 `extract_js_calls`이 정확히 판별하므로 위양성은 성능 손실만
  발생(무해).

### D. SugarCube 스냅샷 캐싱 (효과: 미미, 위험: 낮)

`load_sugarcube_snapshot`은 이미 JSON 파일을 읽는 것이라 빠르다
(0.06s). 병목이 아니므로 우선순위 낮음.

### E. 테스트 분리 (효과: 피드백 루프, 위험: 낮)

`test_macro_audit`의 32개 빠른 테스트와 2개 느린 통합 테스트를 분리한다.
`unittest`의 `@unittest.skipUnless`로 환경 변수(예: `DOLKR_SLOW`)가
설정된 경우만 통합 테스트를 실행.

- 일상적 개발 피드백: 0.2s.
- CI/전체 검증: `DOLKR_SLOW=1`로 전체 실행.
- 단점: 통합 테스트가 기본적으로 안 돌면 회귀가 늦게 발견될 수 있으므로
  A/B/C를 먼저 적용해 전체가 1s 이내가 되면 이 방안은 불필요.

## 권장 순서

1. **A** (캐싱): 예상 4.96s → ~2.6s, 구현 가장 단순, 위험 낮.
2. **B** (`find` 기반 후보 필터): 추가 ~2.6s → ~1.5s, 위험 낮.
3. 필요하면 **C**: 추가 ~1.5s → ~1.0s.
4. **E**는 A/B/C 적용 후 평가.

## 적용 결과: A (2026-08-07)

`_extract_game_js_calls_cached`(`lru_cache(maxsize=64)`)를 두어
`extract_game_specs`와 `extract_game_dynamic`이 동일 game JS 파싱 결과를
공유하도록 했다. `maxsize=64`로 잡은 이유는 `tempfile` 기반 fixture 테스트가
매번 다른 경로를 캐시 키로 넣으므로, maxsize가 작으면 실제 `game/` 경로의
캐시가 밀려나기 때문이다.

```text
적용 전: 112 tests in 4.832s  (real 4.96s)
적용 후: 112 tests in 1.181s  (real 1.33s)
감소: 73%
```

병목 테스트 2개:

| 테스트 | 적용 전 | 적용 후 |
|---|---:|---:|
| `test_audit_report_is_deterministic` | 3.65s | 1.05s (첫 JS 스캔) |
| `test_repo_manifest_passes_audit` | 2.66s | ~0s (캐시 적중) |

corpus_verify 및 macro_audit audit 명령에는 영향 없음(exit 0 유지).

잔여: 첫 JS 스캔 1.1s가 남아있다. **B**(`find` 기반 후보 필터)를 적용하면
이것도 줄일 수 있다.

## corpus_verify 소요 (참고)

```text
$ time python3 -m pretranslation_cst.corpus_verify --root game
real 1m39s
```

이는 16,135개 passage를 파싱/mask/restore하는 것이므로 테스트와 별개.
T1 이후에도 동일(1m45s). per-passage 성능은 회귀 없음.

## 검증

각 방안 적용 후:

```bash
python3 -m unittest discover -s tests  # 소요 시간 측정
python3 -m pretranslation_cst.corpus_verify --root game  # exit code 0
```

audit 결과(GRAMMAR manifest 통과 여부)가 변하지 않아야 한다.