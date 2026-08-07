# Value-Kind Residual Report

Generated 2026-08-07 from the current parser and the canonical `game/**/*.twee`
corpus. Batch 2 (T2 value-kind schema residual cleanup) applied on top of the
T1 + batch 1 baseline (commit 8098f0c).

## Corpus Metrics

| Metric | Batch 1 | Batch 2 |
|---|---:|---:|
| files | 642 | 642 |
| passages/rows | 16,135 | 16,135 |
| unclassified arguments | 20,855 | 18 |
| residual macro/index count | 870 | 16 |
| exposed segments | 529,932 | 530,281 |
| placeholders | 527,987 | 528,336 |
| lossless restorations | 16,135/16,135 | 16,135/16,135 |

Note: the `link_label` increase (32,796 -> 32,908) comes from the concurrent
square-markup dynamic-label parser change; the `macro_arg` increase
(715 -> 952) comes from the batch 2 `prose_text` string-literal
classifications. `plain_text` is unchanged (496,421).

Diagnostic counts:

| Diagnostic | Before | After |
|---|---:|---:|
| `unclassified_argument` | 20,855 | 18 |
| `invalid_macro_name` | 5 | 5 |
| `malformed_macro` | 1 | 1 |
| `unclosed_container` | 2 | 2 |
| `unterminated_comment` | 2 | 2 |

The raw-expression exclusion set (`set`, `run`, `print`, `=`, `-`, `if`,
`elseif`, `for`, `unset`) has zero unclassified diagnostics before and after.

## Batch 2 Classifications

854 of 870 residual macro/index entries were classified with
`definition` (JS `DefineMacro`/`Macro.add` signature or twee widget `_args`
usage) or `call` (inspected call-site values) evidence. No `llm` evidence was
added in this batch.

### SugarCube built-ins (grammar-registered, call evidence)

`radiobutton[1..2]`, `checkbox[1..3]`, `case[3..8]`, `link[1]`, `timed[0]`,
`listbox[1]`, `dialog[0..2]`, `linkreplace[0]`, `replace[1]`,
`addclass[0..1]`, `removeclass[0..1]`, `icon[1]` -> structural /
`prose_text` (dialog title, link text are string literals).

### JS stat macros (definition evidence)

All `[0]` numeric-amount stat macros -> structural: `tiredness`, `def`,
`status`, `sub`, `grace[0]`, `willpower`, `detention`, `awareness`, `control`,
`livestock_obey`, `hallucinogen`, `hope`, `purity`, `drugs`, `rng`, `alcohol`,
`corruption`, `suspicion`, `combattrauma`, `wolfDefiant`, `reb`, skill macros
(`*skill`), sensitivity macros (`*_sensitivity`), wetness macros
(`*wet`), `lewdity`, `lactation_pressure`, `locker_suspicion`,
`masturbationAudienceIncrement`, `earSlimeDaily`, `skulduggery`, `prof[1]`,
`insecurity[1]`, `acceptance[1]`, `world_corruption[1]`, `addevent[1]`,
`ampm`, `formatmoney`, `numberslider`, `passTimeUntil`, `tanningGainOutput`,
`tanningPenaltiesOutput`, `carriedClear[0]` (slot key -> arbitrary_text),
`timeTrackingStart[0]`/`timeTrackingManual[0]` (source key ->
arbitrary_text), `pluralise[0]` (count -> structural), `pluralise[1..2]`
(singular/plural word, string literal -> `prose_text`), `wearProp[1..2]`
(colour keys -> arbitrary_text), `recordSperm[0]` (JS object literal ->
structural), `badEndTracking[1..4]`/`badEndTrackingEnd[1..8]` (JS object
literal tokens -> structural).

Pregnancy macros (definition evidence): `recordVaginalSperm[0..2]`,
`recordAnusSperm[0..2]` (target/owner -> named_npc, spermType ->
arbitrary_text), `playerPregnancy[0..5]` (npc -> named_npc, type ->
arbitrary_text, genital -> body_part, flags -> structural),
`endNpcPregnancy[0..2]`/`endPlayerPregnancy[0..1]` (locations),
`setKnowsAboutPregnancy[0..2]`, `setBabyIntro[0..2]`,
`removeBabyIntro[0..2]`, `setTalkedAboutPregnancy[0..1]` (mother/recipient ->
named_npc), `impregnateParasite[0..2]`, `fertiliseParasites[0]`.

### Twee widgets (definition evidence)

- NPC index args -> structural: `beasttype[0]`, `bhis/bHe/bhim/bhe/bHis/bHes/
  bhes/bhimself/bboy/beastgender/beastsplural[0]`, `personselect[0]`,
  `clearsinglenpc[0]`, `npcPenis/npcVagina/npcChest/npcGenitals/npcPenisSimple
  [0]`, `hand_gag[0]`, guard/inmate widgets
  (`methodical_guard` etc. `[0]`, with `[1]` cap/apo/capo key ->
  arbitrary_text), `generate*` slot widgets.
- NPC references -> named_npc: `npcUndressText[0]`, `npcClothesText[0]`,
  `npcRevealText[0]`, `npcClothesType[0]`, `npcClothesName[0]`,
  `setNPCStrapon[0]`, `give_gift[0]`, `canteenlunchoptions[0]`,
  `schoolWalkChat[0..1]`, `foresthuntstart[0]`, `babyIntro[0]`,
  `pregnancyFeats[0]`, `bellyDescription[1]`, statDisplay `g/l` widgets
  (`gperlove`, `glust`, `gglove`, `llove`, `ldom`, ... `[0]`).
- Body part keys -> body_part: `bodypart[0]`, `tattoo[0]`,
  `bodywriting_clear[0]`, `add_bodywriting[0]`, `parasite[0]`, `bruise[0]`,
  `bodywriting_npc_*[0]`, `sex[1]`, `takeTempleVirginity[1]`,
  `moveCreature[3]`, `playerPregnancy[3]`, `impregnateParasite[2]`.
- Clothing -> clothing: `leash[0]`, `genitalswear[0]`, `ringswear[0]`,
  `clothingicon[0]`, `steal[0]`, `lowersteal[0]`, `feetsteal[0]`,
  `underlowersteal[0]`, `is[0]`, `A[0]`.
- Farm widgets: `farm_text*[0..1]`, `farm_he/He/his/him/His[0..1]`,
  `farm_gen[0]` (animal key -> arbitrary_text), `farm_*` amounts ->
  structural.
- Food/ingredient keys -> arbitrary_text: `recipe_name[0..1]`,
  `ingredientsSuppliesSteal[0..9]`, `ingredientsSupplied[1..9]`,
  `tending_pick[0]`, `recipe_exam_description[0]`.
- Keys/selectors -> arbitrary_text: `canvas-model-override[0..1]`,
  `machine_init[0..4]`, `prop[0..3]`, `drench[0..2]`, `water[0]`,
  `skul_dock_*`, `*difficulty[2]` hide keys, `skill_difficulty[1]`,
  `vore_img[0]`, `danceStudioIntro[0]` (passage name), `beastejaculation[0]`,
  `fameexhibitionism[1]` and other fame `[1]` media-type keys, `fame[0..1]`,
  `fameProse[0]`, `famerape[0..2]`, `gwylan*` keys, `pubfame*`,
  `avery_mansion_*` room keys, `bird_loot[0]`, `flight_hunt_get[0..5]`,
  `prison_rep[0]`, `pirate_status[1]`, `skulduggeryuse[1]`, `hc*` keys,
  `wraith` keys, `deskText/tableText[0]`, `passagestrip[0]`,
  `openinghours[0..1]` (hours -> structural), `map[0..1]` (location + mode
  key), `estate_init[0]`, `islandBuildOption[0]`, `towerBuildOption[0]`,
  `plots_init[0..4]`, `add_plot[0..3]`, `clear_plot[0..1]`,
  `display_plot[0]` (locations).
- `prose_text` (string literals only): `pluralise[1..2]`,
  `CosmeticsGenericDepartment[1,2,8]`, `linkreplace[0]`, `dialog[0]`,
  `sydneyBodywriting[0]`, `genitalsandbreasts[0..1]`, `add_bodywriting[1]` is
  a bodywriting key (arbitrary_text), not prose.
- Flags/amounts -> structural: `tentaclestart[0..1]`, `makeAbomination[0..1]`,
  `struggle_*`, `bird_pass[0]`, `wraith_pass[0]`, `tentacle_forest_pass[0]`,
  `island_pass[0]`, `photo_*`, `rentdue[0]`, `rentduerobin[0]`,
  `blackjack*`, `defiance[0..1]`, `submission[0]`, `violence_noncombat[0..3]`,
  `babyRent[0]`, `kylar_parents_trust[0]`, `island_tide[0]`,
  `islander_language[0]`, `nectarfed[0]`, `semen*swallowedstat[0]`,
  `orgasmcount[0]`, `angelTransform[0]`, `sleep[0]`, `pussy/undies/genitals/
  penis[0]`, `ruined` family, `storeon*[0]` (store location key ->
  arbitrary_text), `generalSend[3]`, `underlowersend[3]`, `facesend[0..1]`.

### Batch-1 key canonicalisation

Nine batch-1 entries were stored under camelCase keys (`bHe`, `bHes`, `bHis`,
`creatureActivity`, `farm_He`, `farm_His`, `generateNPC`, `generateRole`,
`ordinalList`) while the parser looks up `node.name.lower()`; those keys never
matched. They were renamed to lowercase so their classified args take effect
(`generateRole[0..2]` 396 rows and `generateNPC[0..4]` 36 rows were cleared
this way).

## Prioritized Deltas

All entries below are `macro[index]: before -> after` residual counts.

| Entry | Delta |
|---|---:|
| `beasttype[0]` | 542 -> 0 |
| `tiredness[0]` | 506 -> 0 |
| `fameexhibitionism[0]` | 400 -> 0 |
| `def[0]` | 371 -> 0 |
| `status[0]` | 316 -> 0 |
| `sub[0]` | 289 -> 0 |
| `physique[0]` | 263 -> 0 |
| `recipe_name[0]` | 260 -> 0 |
| `saveNPC[0]` | 257 -> 0 |
| `saveNPC[1]` | 257 -> 0 |
| `beastNEWinit[0]` | 250 -> 0 |
| `beastNEWinit[1]` | 250 -> 0 |
| `farm_text[0]` | 229 -> 0 |
| `grace[0]` | 228 -> 0 |
| `willpower[0]` | 211 -> 0 |
| `pluralise[0]` | 193 -> 0 |
| `pluralise[1]` | 193 -> 0 |
| `bhis[0]` | 189 -> 0 |
| `bird_pass[0]` | 181 -> 0 |
| `detention[0]` | 173 -> 0 |
| `canvas-model-override[0]` | 163 -> 0 |
| `athleticsdifficulty[0]` | 157 -> 0 |
| `bHe[0]` | 151 -> 0 |
| `generateRole[0]` | 132 -> 0 |
| `generateRole[1]` | 132 -> 0 |
| `generateRole[2]` | 132 -> 0 |

## Remaining Residual (18 rows / 16 entries) — resolved 2026-08-07

The pre-I2 residual of 18 rows / 16 entries above was revisited after the I2
widget-unopaque change (commit 6236c66) raised `unclassified_argument` to
9,072. The full-corpus value-kind audit (`docs/value-kind-audit-report.md`)
classified every remaining position with call-site or definition evidence:

- `avery_housework_assess[0]` (task key bath/sleep/work, `_args[0] is "work"`
  read by the definition) -> arbitrary_text
- `avery_mansion_interrupt[0]`, `cabintime[0]`, `pubfameComplete[2]`,
  `rutCycle[0]` (flags) -> structural
- `exhibitionist4[0]`, `person3[0]`, `lheat[0]`, `llheat[0]`, `lllheat[0]`
  (values) -> structural
- `generate_methodical_guard[1]`, `pound_text[0]`, `seize_stolen_goods[0]`,
  `shopHuntDebug[0]`, `oral[0]`, `shopHuntInit[0]` (keys/flags) ->
  arbitrary_text

Final state: `unclassified_argument` **0**, `macro_arg` 1,322 -> 1,768
(`option[0]`, `numberStepper[0]`, `actionstentacleadvcheckbox[1]` prose_text
exposures; `avery_mansion_party_speech[1]` demoted to arbitrary_text),
`link_label` and `plain_text` unchanged.

Review queue note: dead positional args that the upstream definition never
reads (e.g. `brat[1]`, `meek[1]`, `submission[1]`) were still classified with
call-site evidence (NPC index / body-target values) where the meaning was
determinable; positions with no evidence remain out of scope for value-kind
entries.
