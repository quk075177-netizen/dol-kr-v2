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
- [파서 구조 개선 로드맵](docs/parser-remediation-roadmap.md)
- [CST 완성 진행 계획](docs/cst-completion-plan.md)
- [value-kind 분류 품질 검수 로드맵](docs/value-kind-audit-roadmap.md)
- [시맨틱 롤 조사 로드맵](docs/semantic-role-roadmap.md)
- [번역 유닛 분할 전략](docs/chunking-strategy.md)
- [문서 인덱스](docs/README.md)

조사 원문과 생성된 데이터셋은 [research/](research/)에 보관한다. `research/`
문서는 근거와 과거 분석 기록이며, 구현 정책의 정본은 `docs/`다.

## 상태

CST 완성. 세 완료 계약(Lossless/Structural/Extraction)이 모두 성립한다.

- 642개 파일, 16,135개 passage round-trip 0 failures, 2회 실행 byte-identity
- `unclassified_argument` 18건으로 수렴 (raw expression 제외, parsed
  positional residual만)
- standalone `[[...]]`와 string-form `<<link "Label" "Target">>` 정적 라벨이
  tree에 leaf로 연결되어 parent context를 가진다
- `link_label` 32,908 / `macro_arg` 952 / `plain_text` 496,421 노출

자세한 진행 기록은 [docs/cst-completion-plan.md](docs/cst-completion-plan.md).

## 사용 방법

환경은 [uv](https://docs.astral.sh/uv/)로 관리한다. 첫 실행 전:

```bash
uv sync --extra dev   # .venv 생성 + 의존성 설치 (Vertex AI SDK 포함)
```

이후 모든 명령은 `uv run`으로 실행한다. 아래 명령어로 전체 과정을
실행한다. 모든 명령은 작업 디렉토리(`dol-kr/`)에서 실행한다.

### 1. 전체 번역 대상 추출하기 (JSONL 생성)

```bash
uv run python -m pretranslation_cst.cli game --output /tmp/dolkr-cst.jsonl
```

`game/` 디렉토리의 모든 `.twee` 파일을 읽어서, 각 passage의 트리 구조와
마스킹된 텍스트를 JSONL 한 줄씩으로 저장한다. 번역 API에 넣기 전의
기본 산출물이다.

### 2. 전체 검증하기 (회귀 확인)

```bash
uv run python -m pretranslation_cst.corpus_verify --root game
```

642개 파일 전체를 파싱·마스킹·복원해서 원본과 byte-exact인지, 트리 구조가
유효한지, 진단 수치가 baseline과 일치하는지 확인한다. `exit code 0`이면
이상 없다는 뜻이다. 파일은 병렬로 처리된다(`--workers 1`로 순차 실행
가능).

### 3. 매크로 문법 감사하기

```bash
uv run python -m pretranslation_cst.macro_audit audit
```

`macro-grammar.json`이 SugarCube 원본과 게임 JS의 매크로 정의와
일치하는지 검사한다. `--corpus`를 붙이면 전체 corpus 파싱까지 추가한다.

### 4. 테스트 실행하기

```bash
uv run python -m unittest discover -s tests
```

120개 단위 테스트를 실행한다.

### 5. 번역 파일럿 (Vertex AI Gemini)

```bash
uv run python -m translation.pilot --passage-name "Ocean Breeze" --max-units 10
```

parse → mask → chunk → Gemini 번역 → restore 전 과정을 실행한다.
ADC 인증(`gcloud auth application-default login`)이 필요하다. 프로젝트와
모델은 `translation/client.py` 상단 상수로 설정한다.

### 산출물 해석

JSONL 한 줄은 하나의 passage다. 각 줄은 `cst`(트리 구조)와 `mask`(노출된
텍스트 + placeholder)로 구성된다.

- `mask.exposed_segments`: 번역 대상 텍스트. `link_label`, `macro_arg`,
  `plain_text` 종류가 있다.
- `mask.placeholders`: 번역하면 안 되는 부분. 원본 텍스트와 byte span을
  가지고 있어서 번역 후 원위치에 복구할 수 있다.
