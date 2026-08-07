from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pretranslation_cst.macro_audit import (
    AuditReport,
    EffectiveSpec,
    _drift_compare,
    audit_corpus,
    audit_manifest,
    audit_sugarcube_drift,
    extract_game_specs,
    extract_js_calls,
    extract_sugarcube_specs,
    load_sugarcube_snapshot,
    resolve_effective_specs,
    sugarcube_specs_to_payload,
)

ROOT = Path(__file__).parents[1]
GRAMMAR = ROOT / "pretranslation_cst/data/macro-grammar.json"
ALLOWLIST = ROOT / "pretranslation_cst/data/macro-grammar-audit-allowlist.json"


class ExtractJsCallsTests(unittest.TestCase):
    def _extract(self, text: str) -> dict[str, EffectiveSpec]:
        calls = extract_js_calls(text, "fixture.js")
        return resolve_effective_specs(calls)

    def test_skip_args_true_is_raw(self) -> None:
        specs = self._extract('Macro.add("set", { skipArgs: true, handler() {} });')
        self.assertEqual(specs["set"].main_raw, True)
        self.assertEqual(specs["set"].container, False)

    def test_tags_null_is_container_without_branches(self) -> None:
        specs = self._extract('Macro.add("foldout", { tags: null, handler() {} });')
        self.assertEqual(specs["foldout"].container, True)
        self.assertEqual(specs["foldout"].tags, ())
        self.assertEqual(specs["foldout"].main_raw, False)

    def test_skip_args_array_makes_only_named_tags_raw(self) -> None:
        specs = self._extract(
            'Macro.add(["cycle", "listbox"], { skipArgs: ["optionsfrom"], tags: ["option", "optionsfrom"] });'
        )
        self.assertEqual(specs["cycle"].main_raw, False)
        self.assertEqual(specs["cycle"].tag_mode("option"), "parsed")
        self.assertEqual(specs["cycle"].tag_mode("optionsfrom"), "raw")

    def test_skip_args_containing_self_is_raw_main(self) -> None:
        specs = self._extract(
            'Macro.add("switch", { skipArgs: ["switch"], tags: ["case", "default"] });'
        )
        self.assertEqual(specs["switch"].main_raw, True)
        self.assertEqual(specs["switch"].tag_mode("case"), "parsed")

    def test_skip_args_true_applies_to_all_tags(self) -> None:
        specs = self._extract('Macro.add("if", { skipArgs: true, tags: ["elseif", "else"] });')
        self.assertEqual(specs["if"].main_raw, True)
        self.assertEqual(specs["if"].tag_mode("elseif"), "raw")

    def test_alias_copies_target_spec(self) -> None:
        specs = self._extract(
            'Macro.add("set", { skipArgs: true, handler() {} });\n'
            'Macro.add("run", "set");'
        )
        self.assertEqual(specs["run"].alias_of, "set")
        self.assertEqual(specs["run"].main_raw, True)

    def test_delete_then_add_is_override(self) -> None:
        specs = self._extract(
            'Macro.add(["button", "link"], { tags: null });\n'
            'Macro.delete(["button", "link"]);\n'
            'Macro.add(["button", "link"], { tags: null });'
        )
        self.assertEqual(specs["button"].container, True)

    def test_define_macro_tags_and_skip_args_parameters(self) -> None:
        specs = self._extract('DefineMacroS("svg", fn, null, false, true);\nDefineMacro("leaf", fn);')
        self.assertEqual(specs["svg"].container, True)
        self.assertEqual(specs["svg"].main_raw, False)
        self.assertEqual(specs["leaf"].container, False)

    def test_stat_display_create_is_leaf(self) -> None:
        specs = self._extract('statDisplay.create("lgrace", expectedRank => 1);')
        self.assertEqual(specs["lgrace"].container, False)

    def test_dynamic_names_are_ignored(self) -> None:
        specs = self._extract('Macro.add(macroName, { tags: null });')
        self.assertNotIn("macroname", specs)

    def test_string_literals_do_not_hide_calls(self) -> None:
        specs = self._extract(
            'const x = "Macro.add(\\"hidden\\", {});";\n'
            '// Macro.add("commented", {});\n'
            'Macro.add("real", { tags: null });'
        )
        self.assertIn("real", specs)
        self.assertNotIn("hidden", specs)
        self.assertNotIn("commented", specs)

    def test_regex_literals_in_options_do_not_break_extraction(self) -> None:
        specs = self._extract(
            'Macro.add("if", { skipArgs: true, tags: ["elseif", "else"], re: /^\\s*if\\b/i, handler() {} });'
        )
        self.assertEqual(specs["if"].main_raw, True)
        self.assertEqual(specs["if"].tags, ("elseif", "else"))

    def test_evidence_points_at_definition(self) -> None:
        calls = extract_js_calls('x = 1;\nMacro.add("thing", {});', "a.js")
        self.assertEqual(calls[0].evidence, "a.js:2")


class SugarcubeExtractionTests(unittest.TestCase):
    def test_pinned_snapshot_round_trip(self) -> None:
        snapshot_path = ROOT / "pretranslation_cst/data/sugarcube-extracted.json"
        self.assertTrue(snapshot_path.exists())
        specs, pinned = load_sugarcube_snapshot(snapshot_path)
        self.assertTrue(pinned)
        self.assertIn("if", specs)
        self.assertEqual(specs["if"].container, True)
        self.assertEqual(specs["if"].main_raw, True)
        self.assertEqual(specs["switch"].tags, ("case", "default"))
        self.assertEqual(specs["silently"].alias_of, "silent")
        self.assertEqual(specs["run"].alias_of, "set")
        self.assertEqual(specs["print"].container, False)
        self.assertEqual(specs["capture"].main_raw, True)
        self.assertEqual(specs["set"].container, False)
        self.assertNotIn("unless", specs)
        self.assertNotIn("style", specs)

    def test_snapshot_payload_round_trip(self) -> None:
        specs, _ = load_sugarcube_snapshot(ROOT / "pretranslation_cst/data/sugarcube-extracted.json")
        payload = sugarcube_specs_to_payload(specs, "unused-root")
        loaded, _ = load_sugarcube_snapshot(payload)
        for key in specs:
            self.assertEqual(loaded[key].to_dict()["main_raw"], specs[key].to_dict()["main_raw"])
            self.assertEqual(loaded[key].to_dict()["tags"], specs[key].to_dict()["tags"])
            self.assertEqual(loaded[key].to_dict()["container"], specs[key].to_dict()["container"])


class AuditManifestTests(unittest.TestCase):
    def _audit(self, grammar: dict, sc_specs: dict, game_js: str = "",
               allowlist: dict | None = None) -> AuditReport:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            grammar_path = root / "grammar.json"
            allowlist_path = root / "allowlist.json"
            grammar_path.write_text(json.dumps(grammar, sort_keys=True), encoding="utf-8")
            allowlist_path.write_text(json.dumps(allowlist or {"entries": {}}, sort_keys=True), encoding="utf-8")
            game_root = root / "game"
            game_root.mkdir()
            if game_js:
                (game_root / "macros.js").write_text(game_js, encoding="utf-8")
            game_specs = extract_game_specs(game_root, sc_specs)
            return audit_manifest(grammar_path, game_root, sc_specs, allowlist_path,
                                  game_specs_override=game_specs)

    def test_consistent_manifest_passes(self) -> None:
        grammar = {
            "version": "test/v1",
            "macros": {
                "set": {"arg_mode": "raw", "source": "sugarcube"},
            },
        }
        sc_specs = {
            "set": EffectiveSpec("set", False, (), True, frozenset(),
                                 source_kind="sugarcube", evidence="src/set-run.js"),
        }
        report = self._audit(grammar, sc_specs)
        self.assertTrue(report.ok)
        self.assertEqual(report.trace["set"]["source"], "sugarcube")

    def test_body_kind_mismatch_fails(self) -> None:
        grammar = {
            "version": "test/v1",
            "macros": {
                "foldout": {"arg_mode": "parsed", "source": "game_js"},
            },
        }
        report = self._audit(grammar, {}, 'Macro.add("foldout", { tags: null });')
        self.assertFalse(report.ok)
        self.assertTrue(any(issue.kind == "body_kind_mismatch" for issue in report.errors))

    def test_arg_mode_mismatch_fails(self) -> None:
        grammar = {
            "version": "test/v1",
            "macros": {
                "capture": {"arg_mode": "parsed", "body_kind": "container", "source": "sugarcube"},
            },
        }
        sc_specs = {
            "capture": EffectiveSpec("capture", True, (), True, frozenset(),
                                     source_kind="sugarcube", evidence="src/capture.js"),
        }
        report = self._audit(grammar, sc_specs)
        self.assertFalse(report.ok)
        self.assertTrue(any(issue.kind == "arg_mode_mismatch" for issue in report.errors))

    def test_tags_mismatch_fails(self) -> None:
        grammar = {
            "version": "test/v1",
            "macros": {
                "timed": {
                    "arg_mode": "parsed", "body_kind": "container", "source": "sugarcube",
                    "tags": {"else": "none"},
                },
            },
        }
        sc_specs = {
            "timed": EffectiveSpec("timed", True, ("next",), False, frozenset(),
                                   source_kind="sugarcube", evidence="src/timed.js"),
        }
        report = self._audit(grammar, sc_specs)
        self.assertFalse(report.ok)
        self.assertTrue(any(issue.kind == "tags_mismatch" for issue in report.errors))

    def test_missing_source_container_fails(self) -> None:
        grammar = {"version": "test/v1", "macros": {}}
        report = self._audit(grammar, {}, 'Macro.add("radiovar", { tags: null });')
        self.assertFalse(report.ok)
        self.assertTrue(any(issue.kind == "source_container_missing_from_manifest" for issue in report.errors))

    def test_missing_source_raw_macro_fails(self) -> None:
        grammar = {"version": "test/v1", "macros": {}}
        report = self._audit(grammar, {}, 'Macro.add("cleareventpool", { skipArgs: true });')
        self.assertFalse(report.ok)
        self.assertTrue(any(issue.kind == "missing_source_raw_macro" for issue in report.errors))

    def test_missing_source_raw_macro_registered_passes(self) -> None:
        grammar = {
            "version": "test/v1",
            "macros": {"cleareventpool": {"arg_mode": "raw", "source": "game_js"}},
        }
        report = self._audit(grammar, {}, 'Macro.add("cleareventpool", { skipArgs: true });')
        self.assertTrue(report.ok)

    def test_missing_source_raw_tag_fails(self) -> None:
        grammar = {
            "version": "test/v1",
            "macros": {
                "cycle": {
                    "arg_mode": "parsed", "body_kind": "container", "source": "sugarcube",
                    "tags": {"option": "parsed"},
                },
            },
        }
        sc_specs = {
            "cycle": EffectiveSpec(
                "cycle", True, ("option", "optionsfrom"), False, frozenset({"optionsfrom"}),
                source_kind="sugarcube", evidence="src/cycle-listbox.js"),
        }
        report = self._audit(grammar, sc_specs)
        self.assertFalse(report.ok)
        raw_tag_issues = [issue for issue in report.errors if issue.kind == "missing_source_raw_tag"]
        self.assertEqual(len(raw_tag_issues), 1)
        self.assertEqual(raw_tag_issues[0].macro, "cycle.optionsfrom")

    def test_missing_source_raw_tag_registered_passes(self) -> None:
        grammar = {
            "version": "test/v1",
            "macros": {
                "cycle": {
                    "arg_mode": "parsed", "body_kind": "container", "source": "sugarcube",
                    "tags": {"option": "parsed", "optionsfrom": "raw"},
                },
                "option": {"arg_mode": "parsed", "source": "sugarcube"},
                "optionsfrom": {"arg_mode": "raw", "source": "sugarcube"},
            },
        }
        sc_specs = {
            "cycle": EffectiveSpec(
                "cycle", True, ("option", "optionsfrom"), False, frozenset({"optionsfrom"}),
                source_kind="sugarcube", evidence="src/cycle-listbox.js"),
        }
        report = self._audit(grammar, sc_specs)
        self.assertTrue(report.ok)

    def test_manifest_entry_without_source_fails(self) -> None:
        grammar = {
            "version": "test/v1",
            "macros": {"phantom": {"arg_mode": "parsed", "source": "sugarcube"}},
        }
        sc_specs = {
            "set": EffectiveSpec("set", False, (), True, frozenset(),
                                 source_kind="sugarcube", evidence="src/set-run.js"),
        }
        report = self._audit(grammar, sc_specs)
        self.assertFalse(report.ok)
        self.assertTrue(any(issue.kind == "manifest_entry_without_source" for issue in report.errors))

    def test_branch_macro_resolved_through_parent(self) -> None:
        grammar = {
            "version": "test/v1",
            "macros": {
                "switch": {
                    "arg_mode": "raw", "body_kind": "container", "source": "sugarcube",
                    "tags": {"case": "parsed", "default": "none"},
                },
                "case": {"arg_mode": "parsed", "source": "sugarcube"},
                "default": {"arg_mode": "none", "source": "sugarcube"},
            },
        }
        sc_specs = {
            "switch": EffectiveSpec(
                "switch", True, ("case", "default"), True, frozenset(),
                skip_args_all=False, source_kind="sugarcube", evidence="src/switch.js"),
        }
        allowlist = {"entries": {"switch.default": [{"kind": "handler_none_args"}]}}
        report = self._audit(grammar, sc_specs, allowlist=allowlist)
        self.assertTrue(report.ok)

    def test_branch_none_mode_requires_allowlist(self) -> None:
        grammar = {
            "version": "test/v1",
            "macros": {
                "switch": {
                    "arg_mode": "raw", "body_kind": "container", "source": "sugarcube",
                    "tags": {"default": "none"},
                },
                "default": {"arg_mode": "none", "source": "sugarcube"},
            },
        }
        sc_specs = {
            "switch": EffectiveSpec(
                "switch", True, ("default",), False, frozenset(),
                source_kind="sugarcube", evidence="src/switch.js"),
        }
        report = self._audit(grammar, sc_specs)
        self.assertFalse(report.ok)
        self.assertTrue(any(issue.kind == "branch_arg_mode_mismatch" for issue in report.errors))

    def test_source_kind_mismatch_fails(self) -> None:
        grammar = {
            "version": "test/v1",
            "macros": {"run": {"arg_mode": "raw", "source": "sugarcube_deprecated"}},
        }
        sc_specs = {
            "run": EffectiveSpec("run", False, (), True, frozenset(),
                                 source_kind="sugarcube", evidence="src/set-run.js"),
        }
        report = self._audit(grammar, sc_specs)
        self.assertFalse(report.ok)
        self.assertTrue(any(issue.kind == "source_kind_mismatch" for issue in report.errors))

    def test_repo_manifest_passes_audit(self) -> None:
        from pretranslation_cst.macro_audit import extract_game_specs, load_sugarcube_snapshot

        snapshot = ROOT / "pretranslation_cst/data/sugarcube-extracted.json"
        sc_specs, _ = load_sugarcube_snapshot(snapshot)
        game_specs = extract_game_specs(ROOT / "game", sc_specs)
        report = audit_manifest(GRAMMAR, ROOT / "game", sc_specs, ALLOWLIST,
                                game_specs_override=game_specs)
        self.assertTrue(report.ok, [issue.to_dict() for issue in report.errors])
        self.assertEqual(len(report.trace), 73)
        self.assertEqual(report.trace["silently"]["source"], "sugarcube_deprecated")
        self.assertEqual(report.trace["button"]["source"], "game_override")
        self.assertEqual(report.trace["radiovar"]["source"], "game_js")
        self.assertEqual(report.trace["case"]["branch_of"], "switch")
        self.assertEqual(report.trace["onclose"]["branch_of"], "dialog")

    def test_audit_report_is_deterministic(self) -> None:
        from pretranslation_cst.macro_audit import extract_game_specs, load_sugarcube_snapshot

        sc_specs, _ = load_sugarcube_snapshot(ROOT / "pretranslation_cst/data/sugarcube-extracted.json")
        game_specs = extract_game_specs(ROOT / "game", sc_specs)
        first = audit_manifest(GRAMMAR, ROOT / "game", sc_specs, ALLOWLIST,
                               game_specs_override=game_specs)
        second = audit_manifest(GRAMMAR, ROOT / "game", sc_specs, ALLOWLIST,
                                game_specs_override=game_specs)
        self.assertEqual(json.dumps(first.to_dict(), sort_keys=True),
                         json.dumps(second.to_dict(), sort_keys=True))


class SugarcubeDriftTests(unittest.TestCase):
    def test_drift_detects_changed_tags(self) -> None:
        live = {
            "if": EffectiveSpec("if", True, ("else",), True, frozenset(),
                                source_kind="sugarcube", evidence="live/if.js"),
        }
        snapshot = {
            "if": EffectiveSpec("if", True, ("else", "elseif"), True, frozenset(),
                                source_kind="sugarcube", evidence="src/if.js"),
        }
        issues = audit_sugarcube_drift(Path("/nonexistent"), snapshot)
        # drift is computed against extracted live specs; provide a fake root by
        # testing the pure comparison through a synthetic live extraction instead.
        from pretranslation_cst.macro_audit import _drift_compare

        issues = _drift_compare(live, snapshot)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].kind, "sugarcube_drift")
        self.assertEqual(issues[0].detail, "tags")

    def test_repo_snapshot_matches_live_sugarcube_when_available(self) -> None:
        live_root = Path("/tmp/opencode/sugarcube-2")
        if not live_root.exists():
            self.skipTest("pinned SugarCube checkout not present")
        snapshot_specs, _ = load_sugarcube_snapshot(
            ROOT / "pretranslation_cst/data/sugarcube-extracted.json")
        live_specs = extract_sugarcube_specs(live_root)
        issues = _drift_compare(live_specs, snapshot_specs)
        self.assertEqual(issues, [], [issue.to_dict() for issue in issues])


class CorpusAuditTests(unittest.TestCase):
    def _run(self, grammar: dict, twee: str) -> tuple[dict[str, int], list]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            grammar_path = root / "grammar.json"
            grammar_path.write_text(json.dumps(grammar, sort_keys=True), encoding="utf-8")
            (root / "passage.twee").write_text(twee, encoding="utf-8")
            game_specs = {
                "radiovar": EffectiveSpec("radiovar", True, (), False, frozenset(),
                                          source_kind="game_js", evidence="ui-radiovar.js"),
                "set": EffectiveSpec("set", False, (), True, frozenset(),
                                     source_kind="sugarcube", evidence="set-run.js"),
            }
            counts, issues, files, passages = audit_corpus(root, grammar_path, game_specs)
            self.assertEqual(files, 1)
            self.assertEqual(passages, 1)
            return counts, issues

    def test_missing_container_in_manifest_is_registry_gap(self) -> None:
        grammar = {"version": "t", "macros": {"set": {"arg_mode": "raw", "source": "sugarcube"}}}
        counts, issues = self._run(
            grammar,
            ':: T\n<<radiovar "$x" 1>>on<</radiovar>>\n',
        )
        self.assertEqual(counts.get("mismatched_close"), 1)
        self.assertTrue(any(issue.kind == "registry_gap_mismatched_close" for issue in issues))

    def test_registered_container_has_no_registry_gap(self) -> None:
        grammar = {
            "version": "t",
            "macros": {
                "set": {"arg_mode": "raw", "source": "sugarcube"},
                "radiovar": {"arg_mode": "parsed", "body_kind": "container", "source": "game_js"},
            },
        }
        counts, issues = self._run(
            grammar,
            ':: T\n<<radiovar "$x" 1>>on<</radiovar>>\n',
        )
        self.assertNotIn("mismatched_close", counts)
        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
