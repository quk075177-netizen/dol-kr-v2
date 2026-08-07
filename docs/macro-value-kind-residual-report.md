# Value-Kind Residual Report

Generated 2026-08-07 from the current parser and the canonical `game/**/*.twee`
corpus. Existing JSONL artifacts were not overwritten.

## Corpus Metrics

| Metric | Before | After |
|---|---:|---:|
| files | 639 | 639 |
| passages/rows | 16,135 | 16,135 |
| unclassified arguments | 44,240 | 23,206 |
| residual macro count | 612 | 598 |
| residual macro/index count | 919 | 891 |
| exposed segments | 529,674 | 529,674 |
| lossless restorations | 16,135/16,135 | 16,135/16,135 |

Diagnostic counts were unchanged except for the intended residual reduction:

| Diagnostic | Before | After |
|---|---:|---:|
| `unclassified_argument` | 44,240 | 23,206 |
| `invalid_macro_name` | 5 | 5 |
| `malformed_macro` | 1 | 1 |
| `unclosed_container` | 2 | 2 |
| `unterminated_comment` | 2 | 2 |

The raw-expression exclusion set (`set`, `run`, `print`, `=`, `-`, `if`,
`elseif`, `for`, `unset`) had zero unclassified diagnostics before and after.
The stale positional `if[0]` mapping entry was also removed; all raw macros now
have no value-kind positional entries.
The after verification had zero schema violations and zero malformed JSONL rows.

## Follow-up Batch 1

After the initial schema migration, an evidence-backed batch classified only
structural arguments and one player-facing explanation:

- structural: `case[1..2]`, `addinlineevent[1]`, `bodyliquid[1..2]`, `note[1]`,
  `transform[1]`, `specialClothesUnlock[1]`
- `prose_text`: `insufficientStat[1]`

Against the previous corpus baseline, this batch changed diagnostics from
`23,216` total (`unclassified_argument` `23,206`) to `20,865` total
(`unclassified_argument` `20,855`). Exposed segments changed from
`529,674` to `529,864`: `macro_arg` `525 -> 715`, while `link_label` and
`plain_text` remained unchanged. Restore and tree invariant failures remained
zero.

## Prioritized Deltas

All entries below are `macro[index]: before -> after` residual counts.

### base-combat

| Entry | Delta |
|---|---:|
| `spray[0]` | 6 -> 0 |
| `moneyGain[0]` | 1 -> 0 |
| `moneyGain[1]` | 1 -> 0 |
| `moneyGain[2]` | 1 -> 0 |
| `moneyGain[3]` | 1 -> 0 |
| `beast[0]` | 1 -> 0 |
| `violence[0]` | 1 -> 0 |
| `neutral[0]` | 1 -> 0 |

### overworld-town

| Entry | Delta |
|---|---:|
| `pass[0]` | 3,329 -> 0 |
| `pass[1]` | 210 -> 0 |
| `stress[0]` | 2,568 -> 0 |
| `trauma[0]` | 1,422 -> 0 |
| `arousal[0]` | 952 -> 0 |
| `arousal[1]` | 314 -> 0 |
| `money[0]` | 558 -> 0 |
| `money[1]` | 434 -> 0 |
| `neutral[0]` | 849 -> 0 |
| `neutral[1]` | 4 -> 0 |
| `loadNPC[0]` | 336 -> 0 |
| `loadNPC[1]` | 336 -> 0 |
| `pain[0]` | 625 -> 0 |
| `crimeUp[0]` | 282 -> 0 |
| `crimeUp[1]` | 281 -> 0 |
| `crimeUp[2]` | 4 -> 0 |
| `violence[0]` | 563 -> 0 |
| `violence[1]` | 1 -> 0 |
| `violence[2]` | 1 -> 0 |
| `violence[3]` | 1 -> 0 |
| `printmoney[0]` | 487 -> 0 |
| `printmoney[1]` | 8 -> 0 |

The remaining residual list is the complete tab-separated artifact
`/tmp/opencode/agent1-after-final-residuals-20260807.tsv` (891 macro/index rows),
generated from `agent1-after-final-20260807.jsonl`. The highest remaining entries are:

```text
case[1] 594
beasttype[0] 542
tiredness[0] 506
addinlineevent[1] 443
fameexhibitionism[0] 400
def[0] 371
status[0] 316
bodyliquid[1] 304
sub[0] 289
physique[0] 263
recipe_name[0] 260
savenpc[0] 257
savenpc[1] 257
beastnewinit[0] 250
beastnewinit[1] 250
bhe[0] 239
farm_text[0] 229
grace[0] 228
note[1] 224
bhis[0] 213
```
