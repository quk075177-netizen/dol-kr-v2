# 3-way match (골든 데이터셋)와 post(조사) 정보 취합

기준일: 2026-08-07

research/ 문서에서 "3-way match"와 "post(조사)" 관련 사실을 취합한
요약본이다. 원본 문서는 각 절에 연결돼 있다.

---

## Part 1. 3-way match (원문 / vanilla / KO)

### 1.1 정의

**3-way match (triple-match)** 는 현재 Plus `game/`의 passage를 기준으로
vanilla 0.5.10.12와 KO HTML(0.5.10.12 기반)을 **3원으로 매칭**해, 원문과
참조 번역이 **구조(skeleton)까지 일치**하는 passage를 골라낸 것이다.
번역 파이프라인의 QA·glossary 검증에 사용할 수 있는 **원문-참조번역 쌍**
데이터다.

- 출처: `research/golden-dataset.md`
- 데이터: `research/golden/corpus-triple-match.jsonl` (7,206 passage)

### 1.2 매칭 기준

| 축 | 상태값 | 의미 |
|---|---|---|
| vanilla | `identical` | 원문 == vanilla 본문 |
| vanilla | `changed` / `missing` / `unknown` | vanilla와 다름/없음/판별 불가 |
| KO | `match` | KO 번역이 **구조 skeleton까지** 일치 (triple-match 성립) |
| KO | `structure_mismatch` | 번역이 구조를 바꿈 (파서가 잡아야 할 케이스) |
| KO | `missing` / `parse_blocked` | KO 없음/파싱 불가 |

triple-match 성립 조건: `vanilla_status == identical` **AND**
`ko_status == match`.

### 1.3 규모 (Twee)

| 지표 | 수 | 비율 |
|---|---:|---:|
| 전체 passage | 16,135 | 100% |
| vanilla identical | 13,113 | 81.3% |
| KO 번역 보유 | 15,421 | 95.6% |
| **triple-match** | **7,206** | **44.7%** |
| KO structure_mismatch | 4,475 (held 중) | — |

### 1.4 레코드 스키마 (corpus-triple-match.jsonl)

```json
{
  "passage_name": "Abduction Hospital Corridor",
  "source_path": "overworld-town/loc-hospital/abduction.twee",
  "source_body": "<<effects>><<set $lock to random(0, 1000)>>\n\nYou run down...",
  "source_sha256": "...",
  "vanilla_status": "identical | changed | missing | unknown",
  "vanilla_body": "vanilla 0.5.10.12 본문 (매칭 시)",
  "ko_status": "match | structure_mismatch | missing | parse_blocked",
  "ko_skeleton_sha256": "...",
  "ko_body": "KR 번역본 (존재 시)",
  "state": "eligible | held | empty | excluded | unknown",
  "hold_reason_codes": ["..."]
}
```

### 1.5 JS 대응 (js-extraction-verification.md)

| 지표 | 수 |
|---|---:|
| JS 번역 쌍 (`js-corpus-triple-match.jsonl`) | 7,703 |
| 영어 유지(번역 안 함) | 39,586 |
| 한국어 문자열 | 9,373 |
| 영어 유지율 | 99.6% |

`status`: `triple_match | english_kept | korean_only`

### 1.6 활용

- **QA**: 원문-참조번역 쌍으로 Gemini 번역 결과 비교·스코어링
- **glossary 검증**: 참조 번역의 표시명과 glossary `display_ko` 대조
- **조사 마커 분석 입력**: KO body의 `【 】` 마커는 triple-match passage에
  대부분 포함 (ko-marker-analysis.md §6)
- **파서 회귀**: `structure_mismatch`는 번역이 구조를 바꾼 실제 사례 —
  파서/마스킹이 이를 허용하는지 검증 대상

### 1.7 주의

- `source_body`는 현재 Plus 원문 그대로 — 성인 콘텐츠 포함. Git 제외
  개인 로컬 데이터로 취급.
- vanilla/KO body는 passage name이 정확히 일치할 때만 포함.

---

## Part 2. post(조사) — 받침 판정과 조사 치환

### 2.1 정의

`post`는 한국어 조사(은/는, 이/가, 을/를…) 선택에 필요한 **받침
판정번호**다. dol-kr `trPost.js`의 `getPostNum` 규칙을 그대로 따른다.

| post | 의미 | 예 |
|---:|---|---|
| 0 | 받침 있음 | 집**이**, 밥**을** |
| 1 | 받침 없음 | 학교**가**, 책**을** |
| 2 | ㄹ받침 | 서울**이**? — ㄹ은 `을/를`에서는 `를`로 특수 처리 |

### 2.2 getPostNum 규칙 (translation-workflow.md §5)

1. **한글 끝**: `jong = (code - 0xAC00) % 28`
   - `jong == 0` → 받침X (post 1)
   - `jong == 8` → ㄹ받침 (post 2)
   - 그 외 → 받침O (post 0)
2. **숫자 끝**: 표 `[0, 2, 1, 0, 1, 1, 0, 2, 2, 0]` (숫자 0~9)
3. **그 외 (라틴/괄호/기호)**: 미정 — 데이터 아카이브에서는 `null`
   (ko-marker 분석에서는 기본 받침X로 처리)

### 2.3 glossary에서의 post (glossary-schema.md)

`research/data/glossary.yml` (glossary-clothing/v1, 1,459 entries):

```json
{
  "key": "amethyst-cocktail",
  "slot": "earrings",
  "name": "amethyst cocktail earrings",
  "display_ko": "자수정 칵테일",
  "post": 2,
  "status": "approved",
  "source": "owner approved 2026-08-07"
}
```

- 전부 자동 계산됨 (`compute_post.py`)
- 분포: 받침O 232, 받침X 1,135, ㄹ받침 92 (미정 0)
- **display_ko가 바뀌면 post 재계산 필요**
- 조사는 `post`로 결정: 은/는, 이/가, 을/를, 과/와, (으)로, 이다 계열

### 2.4 KO HTML의 【 】조사 마커 (ko-marker-analysis.md)

기존 KO 번역(0.5.10.12 기반)은 **조사 자리표시자 방식**을 쓴다. 받침에
따라 달라지는 조사를 `【은는】`처럼 쌍으로 남겨 런타임에 치환한다.

- 마커 포함 passage: **10,765 / 15,431 (69.8%)**
- 마커 총 사용: **83,907회**

| 마커 | 받침O(0) | 받침X(1) | ㄹ받침(2) | 사용 |
|---|---|---:|---:|---:|---:|
| `【은는】` | 은 | 는 | 은 | 37,804 |
| `【이가】` | 이 | 가 | 이 | 30,363 |
| `【을를】` | 을 | 를 | 을 | 12,880 |
| `【와과】` | 과 | 와 | 과 | 1,518 |
| `【으로로】` | 으로 | 로 | 로 | 652 |
| `【이】` | 이 | 이 | 이 | 491 |
| `【아야】` | 아 | 야 | 아 | 133 |
| `【이었였】` | 이었 | 였 | 이었 | 58 |
| 기타 (`【는】`, `【아가】` 등) | — | — | — | 8 |

**핵심 특성**: 마커 앞에 오는 값은 대개 **런타임 출력** (`$worn.upper.name`,
`<<bellyDescription>>`, `<<girl>>`) — 번역 시점에 받침을 모른다.
즉 마커는 "동적 조사 계산 필요" 표시다.

### 2.5 파이프라인 처리 규칙 (재사용 시)

| 상황 | 처리 |
|---|---|
| 마커 뒤가 고정 문자열이고 마커 앞 값의 받침이 결정적일 때 | 받침 계산 후 확정 조사로 치환 (정적) |
| 마커 앞이 런타임 출력(`$var`, `<<print>>`)일 때 | 마커 → particle helper 호출 (동적) |
| `【이】` + 어미(네/구나) | `이다` 계열로 처리 (`이네`/`이구나`) |
| 마커가 없으면 | 조사 그대로 사용 |

**정적/동적 판정**: 마커 앞 텍스트에 런타임 토큰(`$`, `_`, `<<`, `` ` ``)
이 있으면 동적 helper, 순수 한글/고정 문자열이면 정적 치환.

### 2.6 dol-kr 참조 구현 (dol-kr-architecture.md)

- `trPost.js`: `getPostNum()` 받침 0/1/2 판정 + `trPostsList` **26개
  조사 × 3형태** — 일반화 완료, 재사용 가능
- `Post/EasyPost.js`: 305개 `{name, orig_name, is_print}` 테이블을
  eval로 매크로 등록 — 재구축 시 `Macro.add` 직접 호출 권장
- 데이터 오류: post를 수작업 판정하던 805개 → `getPostNum` 자동화 필요

### 2.7 현재 파이프라인과의 관계

- **glossary**: `(slot, key) → display_ko + post` — 의류 표시명
  조사 선택에 직접 사용 가능
- **시맨틱 롤과 결합**: value-kind(무엇인지) + post(받침) + 시맨틱
  롤(문장 내 역할)이 합쳐지면 "로빈이" / "로빈을" 같은 조사 완성 문구를
  생성할 수 있음 (`docs/semantic-role-roadmap.md` S5)
- **번역 출력 규칙**: 새 번역에서는 `【 】` 마커 대신 post 필드 또는
  particle helper 규칙으로 조사를 확정해야 함

---

## 참고 문서 맵

| 주제 | 원본 문서 |
|---|---|
| 골든 3-way 데이터셋 | `research/golden-dataset.md` |
| JS 3-way | `research/js-extraction-verification.md`, `research/js-golden-dataset.md` |
| KO 【 】마커 분석 | `research/ko-marker-analysis.md` |
| post 자동 계산 워크플로우 | `research/translation-workflow.md` §5 |
| glossary post 스키마 | `research/glossary-schema.md` |
| dol-kr 조사 코어 | `research/dol-kr-architecture.md` |
| dol-kr 데이터 post 필드 | `research/dol-kr-translate/README.md` |
| upstream post=null 아카이브 | `research/dolp/README.md` |
| 파이프라인 전체 흐름 | `research/pipeline-design.md` |