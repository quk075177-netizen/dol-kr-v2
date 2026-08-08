# 번역 빌드 체인 구현 피드백 요청

기준일: 2026-08-08
목적: 이번 세션에서 구현한 "번역 결과물 → 게임 빌드 → 브라우저 스모크" 체인의
미흡 지점을 리뷰받기 위한 문서. 코드베이스 전체를 몰라도 읽을 수 있게 작성.

## 1. 이 체인이 하는 일 (맥락 3줄)

이 프로젝트는 영어 게임(Degrees of Lewdity Plus)의 텍스트를 한국어로
번역하는 파이프라인을 만든다. 기존 KO 번역본(3-match 데이터)과 신규 LLM
번역을 **passage 단위 레코드(JSONL)**로 모아, 그것을 원본 게임 트리와
합쳐 **`game_ko/`** 트리를 만들고, Tweego로 컴파일해 실제로 플레이
가능한 **HTML 빌드**를 산출한다. 마지막으로 headless Chromium에서
그 빌드를 열어 "번역이 실제로 잘 들어갔고 게임이 안 깨지는지"를 자동
검증한다.

## 2. 데이터 흐름

```text
work/translations/ko-reuse.jsonl   ← passage 단위 번역 레코드 (3,151건)
        │
        ▼  translation/assemble_game_ko.py
        │  (game/ 전체 복사 + 번역 passage body 스플라이스)
        ▼
game_ko/                            ← 완전한 Tweego 프로젝트 트리
        │
        ▼  build/dol_build.py compile (pinned tweego + 커스텀 SugarCube)
        ▼
build/dol-plus-ko.html              ← 컴파일된 게임
        │
        ▼  browser_smoke.py run --passage-list
        ▼
build/browser-smoke/report.json     ← UI 체크 7종 + passage 전수 검증 결과
```

## 3. 파일 목록과 역할

| 파일 | 역할 | 비고 |
|---|---|---|
| `translation/assemble_game_ko.py` | 레코드 → game_ko/ 어셈블 | 이번 세션 신규 |
| `translation/store.py` | 레코드 저장소 로드/재사용 판정 | 지난 세션 |
| `translation/register_ko_reuse.py` | 3-match KO 번역 → 레코드 등록 | 지난 세션 |
| `build/dol_build.py` | pinned 툴체인 부트스트랩 + tweego 컴파일 | 사용자 제공, ROOT 수정 |
| `build-tools.lock.json` | 툴체인 핀 (sha256 검증) | 사용자 제공 |
| `browser_smoke.py` / `.mjs` | headless Chromium 스모크 | 사용자 제공 + 로컬라이즈 |
| `tests/test_assemble_game_ko.py` | 어셈블러 유닛 테스트 5건 | 신규 |

## 4. 미흡하다고 생각되는 부분 (우선순위순)

### H1. 어셈블이 느리다 — 병렬화/캐싱 없음 (확인됨: 3,151건 ≈ 6분)

- 원인: 파일별로 파싱을 3회 반복 (스플라이스용, verify용 원본, verify용
  결과물). `corpus_verify`는 ProcessPoolExecutor(16 워커)를 쓰는데
  어셈블러는 단일 스레드.
- 제안: 파일 단위 병렬화, 또는 "파싱 1회 + 구조 검증은 레코드 등록 시점에
  이미 한 대칭 검사로 갈음"하는 정책 결정. `--no-verify`는 ~2분까지 줄이지만
  구조 검증이 사라져 위험.

### H2. verify의 구조 검증이 "매크로 토큰 시퀀스" 휴리스틱이다

- `macro_sequence`는 매크로 이름/링크/HTML 태그를 순서대로 뽑아 비교하는
  정규식 핑거프린트다. **중첩 균형, 인자 구조, 실제 보호 스팬은 검증하지
  않는다.** 같은 이름 매크로의 재배치/중첩 변경은 감지 못할 수 있다.
- 등록 단계(`register_ko_reuse._verify_passage`)에는 **우리 파서 기반
  보호 스팬 대칭 검사**(더 강력)가 이미 있는데, 어셈블 시점에는 재사용되지
  않는다.
- 제안: 어셈블 verify를 "원본/결과물 각각 mask → protected span 시퀀스
  비교"로 강화 (이미 존재하는 유틸 `passage_placeholder_signature` 사용).

### H3. 어셈블이 비원자적이다 (실패 시 부분 출력 위험)

- `game_ko/`에 직접 쓴다. 6분짜리 실행이 중간에 죽으면 절반만 번역된
  트리가 남고, 재실행 시 copytree(dirs_exist_ok)가 낡은 파일을 섞을 수
  있다. 임시 디렉터리 + rename 교체가 안전.

### H4. 스모크의 "번역 검증" 기본값이 비어 있다

- `--expect-options-text`를 안 주면 `koreanOptionsApplied`가 항상 true
  (skip). 즉 **옵션 UI가 영어로 회귀해도 기본 실행으로는 못 잡는다.**
- passage-list 파일(`translated-passages.tsv`) 생성 도구가 없어 수동
  생성 중 (레코드에서 한국어 조각 추출). 어셈블러 또는 별도 스크립트로
  자동화 필요.
- 제안: 기본 기대 문자열을 레코드에서 파생하거나, "번역 passage 비율"
  지표(예: 스토리 passage 중 한국어 포함 비율 ≥ N%)를 체크에 추가.

### H5. 스모크 셀렉터가 게임 UI 구조에 강하게 결합

- `#customOverlay`, `#startCaption`, `#ui-dialog-body`, 버튼 이름
  try-both(영문/KO)는 게임 UI 변경에 취약하다. 버튼/오버레이 구조가
  바뀌면 스모크가 무의미하게 실패한다.
- 제안: 셀렉터를 설정 파일로 분리하거나, "존재하면 클릭, 없으면 경고"
  같은 유연한 체크 정책 채택.

### H6. 테스트 커버리지 갭

- 어셈블러 테스트에 **멀티 passage 파일(역순 스플라이스 경로)**,
  **코드 passage 제외**, **레코드 중복(같은 이름 두 레코드)** 케이스가
  없다. 실제로 멀티 스플라이스에서 버그를 만났는데(경계 newline) 픽스처로
  고정되지 않았다.
- browser_smoke의 mjs는 유닛 테스트가 없다 (셀렉터 로컬라이즈 로직 등).

### H7. 레코드 데이터의 일관성 문제를 어셈블러가 떠안고 있다

- 3-match KO body는 trailing newline이 없는 형식이라 어셈블러가 경계
  공백을 보존하는 보정을 한다 (HANDOFF에 기록). **등록 단계에서 body
  경계 구조를 정규화**하는 편이 소비자(어셈블러)의 부담을 줄인다.
- `source_path`/passage 이름이 현재 버전과 다른 낡은 레코드(1건 확인:
  `Widgets Office Lift`)는 조용히 skip된다 — 통계 보고만 하고 원인 추적이
  안 된다.

### H8. 오케스트레이션 부재

- 어셈블 → 컴파일 → 스모크가 3개 커맨드로 분리돼 있다. "한 번에
  검증"하는 진입점(스크립트 또는 Makefile)이 없어 실수 여지가 있다.

## 5. 리뷰어에게 받고 싶은 질문

1. 어셈블 검증 정책: "등록 시점 대칭 검사"만으로 충분한가, 아니면
   어셈블 시점에도 강한 검증(보호 스팬 비교)이 필요한가? (H2, 성능과의
   트레이드오프)
2. passage 단위 스플라이스 방식(원본 트리 복사 + body 교체)이 유지보수
   관점에서 타당한가? 대안(파일 재생성, diff 패치)이 있는가? (H3)
3. 스모크의 검증 목표가 "번역분 검증"인지 "게임 회귀 검증"인지에 따라
   체크 강도가 달라져야 하는데, 현재 7종 + passage-list로 충분한가?
   (H4, H5)
4. 성능(6분)이 문제라면 어디까지 최적화할 가치가 있는가? (H1)
5. 레코드 스토어의 `level`(passage/unit) 혼재 설계 — 장기적으로
   통일/분리 어느 쪽이 나은가? (H7 관련, 문서: `docs/translation-reuse-design.md`)

## 6. 재현 방법

```bash
# 어셈블 (3,151건, ~6분)
uv run python -m translation.assemble_game_ko

# 컴파일 (~2초, 첫 실행은 툴체인 다운로드)
python3 build/dol_build.py compile --force

# 스모크 (~6초)
python3 browser_smoke.py run --html build/dol-plus-ko.html \
  --output build/browser-smoke --passage-list /tmp/opencode/translated-passages.tsv

# 유닛 테스트
uv run python -m unittest discover -s tests
```

산출물: `build/browser-smoke/report.json` (checks + passageList + 에러 목록),
`build/dol-plus-ko.html.build.json` (컴파일 보고).
