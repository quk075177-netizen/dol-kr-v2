# 워커 에이전트 지시문: value-kind 분류 품질 검수

기준: CST 완성 (commit 5602c84), value-kind 1,626개 인자 항목 등록 후

## 공통 기준

- 정본 입력은 `game/**/*.twee`다.
- 기존 `/tmp/opencode/*.jsonl`은 덮어쓰지 않는다. 새 산출물은 새 경로에
  생성한다.
- 모든 변경은 `python3 -m unittest discover -s tests -v`를 통과해야 한다.
- 전 corpus 검증은 `python3 -m pretranslation_cst.corpus_verify --root game`
  로 재현하며, exit code 0이어야 한다.
- parser 변경이 필요한 새 결함을 발견하면 우회 수정하지 말고 source,
  passage, macro, byte span, 최소 fixture와 함께 보고한다.
- 완료 보고에는 before/after diagnostic 및 exposed segment count를
  포함한다.
- `set`, `run`, `print`, `=`, `-`, `if`, `elseif`, `for`, `unset`은 raw
  expression이다. 이들의 공백 token을 value-kind positional argument로
  등록하지 않는다.
- 실패하면 prose로 추정하지 않고 보호 span과 진단을 남긴다.
- 담당 범위 밖 parser refactor를 하지 않는다.
- 문서 정책(`docs/cst-scope.md`, `docs/sugarcube-ground-truth.md`,
  `docs/value-kind-policy.md`, `docs/validation.md`)과 충돌하면 문서를
  우선한다.

## 담당 파일

- `config/macro-value-kind.yml`
- `docs/macro-value-kind-residual-report.md`
- `pretranslation_cst/data/corpus-baseline-v1.json`
- `docs/validation.md` (현재 기대값 갱신만)
- 검수 보고서 (새 파일, `docs/value-kind-audit-report.md`)

## 수정 금지

- `pretranslation_cst/parser.py`
- `pretranslation_cst/grammar.py`
- `pretranslation_cst/square_markup.py`
- `pretranslation_cst/model.py`
- `pretranslation_cst/data/macro-grammar.json`
- `pretranslation_cst/macro_audit.py`
- `pretranslation_cst/corpus_verify.py`
- `pretranslation_cst/masking.py`
- `tests/` 하위 모든 파일

## 현재 기준선

```text
diagnostics 28 total: unclassified_argument 18
segments: link_label 32,908, macro_arg 952, plain_text 496,421
baseline matched=True, exit code 0
```

value-kind config 현황:

```text
1,050개 매크로, 1,626개 인자 항목
kind 분포: structural 570, arbitrary_text 336, (kind 없음) 223,
  named_npc 103, ui_icon 79, clothing 69, body_part 53,
  event_key 40, location 39, prose_text 33
evidence: definition 845, call 288, llm 189 (전부 confidence=high)
```

## 지시

```text
docs/value-kind-audit-roadmap.md의 P1~P5 우선순위를 순서대로 검수하라.

P1. kind 없는 223개 항목 정리:
  - config/macro-value-kind.yml에서 kind 필드가 없는 223개 항목을
    추출하라.
  - 각 항목의 note를 근거로 kind를 부여하거나, note만으로는 판정이
    불가능하면 항목을 제거하라 (제거 시 보호로 fallback됨).
  - "passed to >print()" 같은 note는 structural로 분류하는 것이 적절한지
    실제 호출부를 확인하라.
  - 정리 후 kind 없는 항목이 0개가 되어야 한다.

P2. arbitrary_text 336개 재검토:
  - arbitrary_text kind 항목 중 30개를 무작위 샘플링하여 실제 호출부
    텍스트를 추출하라.
  - 각 텍스트가 번역 대상(prose_text)인지 구조적 인자(structural)인지
    판정하라.
  - 오분류율을 보고하고, 10% 이상이면 전수 재검토를 권고하라.
  - 이 단계에서는 샘플링 검수만 하고, 전수 정정은 별도 배치로 진행한다.

P3. prose_text 33개 노출 검증:
  - prose_text kind로 인해 노출된 macro_arg segment의 실제 텍스트를
    전수 추출하라.
  - 각 텍스트가 사용자 facing 문장/구인지, 내부 식별자가 아닌지
    확인하라.
  - 내부 식별자가 노출되고 있으면 해당 macro/index의 kind를
    structural 또는 arbitrary_text로 강등하라.

P4. 시맨틱 kind 4종(named_npc/clothing/body_part/location) 실사용 검증:
  - 각 kind의 항목 중 15개씩 샘플링하여 실제 호출부 텍스트를 추출하라.
  - 추출된 텍스트가 해당 kind(고유명사/의류/신체부위/장소)와 일치하는지
    확인하라.
  - 오분류율을 보고하라.
  - glossary 매칭 가능성을 평가하라 (해당 텍스트가 glossary 항목 후보로
    적합한지).

P5. LLM 근거 189개 재검증:
  - LLM evidence를 가진 189개 항목 중 30개를 무작위 샘플링하여 실제
    호출부 텍스트를 추출하라.
  - 각 텍스트가 분류된 kind와 일치하는지 수동 확인하라.
  - 오분류율을 보고하라. 10% 이상이면 해당 매크로를 전수 재검토
    대상으로 지정하라.

모든 단계에서:
  - 추출은 corpus에서 직접 수행하고, source path/passage/macro/
    arg index/raw text를 기록하라.
  - config 변경 후 corpus_verify exit 0과 unittest 113개 통과를
    확인하라.
  - baseline 수치가 변하면 corpus-baseline-v1.json과 docs/validation.md를
    갱신하라.
  - 검수 결과를 docs/value-kind-audit-report.md에 단계별로 정리하라.
```

## 완료 기준

- kind 없는 223개 항목이 0개가 됨.
- `arbitrary_text` 샘플링 오분류율 보고.
- `prose_text` 노출 항목이 전부 사용자 facing 텍스트임.
- 시맨틱 kind 4종 샘플링 오분류율 보고.
- LLM 근거 샘플링 오분류율 보고.
- `corpus_verify` exit code 0, baseline 일치.
- `python3 -m unittest discover -s tests -v` 113개 통과 유지.
- 검수 보고서 `docs/value-kind-audit-report.md` 작성.

## 보고 형식

```text
## P1. kind 없는 항목 정리
- before: 223개
- after: 0개
- 정리 내역: structural 부여 N개, 제거 M개, 기타 K개

## P2. arbitrary_text 재검토
- 샘플: 30개
- 오분류: N개 (오분류율 X%)
- 전수 재검토 권고: 예/아니오

## P3. prose_text 노출 검증
- 노출 항목 수: N개
- 사용자 facing: M개
- 내부 식별자 (강등 대상): K개
- 강당 내역: ...

## P4. 시맨틱 kind 실사용 검증
- named_npc: 샘플 15개, 오분류 N개
- clothing: 샘플 15개, 오분류 N개
- body_part: 샘플 15개, 오분류 N개
- location: 샘플 15개, 오분류 N개

## P5. LLM 근거 재검증
- 샘플: 30개
- 오분류: N개 (오분류율 X%)
- 전수 재검토 대상: ...

## before/after
- unclassified_argument: <before> -> <after>
- macro_arg: <before> -> <after>
- link_label: <before> -> <after>
- corpus_verify exit code: 0

## 새 결함 (발견 시)
- source/passage/macro/span/fixture
```