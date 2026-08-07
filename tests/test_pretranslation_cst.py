from __future__ import annotations

import json
import unittest
from pathlib import Path

from pretranslation_cst import mask_passage, parse_file, restore_mask, split_twee


ROOT = Path(__file__).parents[1]
VALUE_KINDS = ROOT / "research/data/macro-value-kind.yml"


class PretranslationCstTests(unittest.TestCase):
    def test_split_preserves_file_and_uses_byte_offsets(self) -> None:
        data = ":: 첫 passage [tag]\n가\n:: second\n내용\n".encode("utf-8")
        source = split_twee(data, "fixture.twee")
        self.assertEqual(len(source.passages), 2)
        self.assertEqual(source.passages[0].name, "첫 passage")
        self.assertEqual(source.passages[0].tags, ["tag"])
        self.assertEqual(data[source.passages[0].body_span.start:source.passages[0].body_span.end], "가\n".encode())
        self.assertEqual(data[source.passages[1].body_span.start:source.passages[1].body_span.end], "내용\n".encode())
        self.assertEqual(source.passages[0].source_span.end, source.passages[1].source_span.start)
        self.assertEqual(data[source.prefix_span.start:source.prefix_span.end], b"")

    def test_macro_quote_and_gt_boundaries(self) -> None:
        body = b':: Test\n<<set $x to "a >> b">>\n<<if $x >> 5>>Hi<</if>>\n'
        source = parse_file(body, "fixture.twee", VALUE_KINDS)
        passage = source.passages[0]
        calls = [node for node in passage.nodes if node.role == "call"]
        self.assertEqual([node.name for node in calls], ["set", "if", "/if"])
        self.assertEqual(body[calls[0].span.start:calls[0].span.end], b'<<set $x to "a >> b">>')
        self.assertEqual(body[calls[1].span.start:calls[1].span.end], b"<<if $x >>")

    def test_only_prose_macro_string_is_exposed(self) -> None:
        body = b':: Test\n<<gagged_speech "C-could you take me with you?">> <<icon "heart.png">>\n'
        source = parse_file(body, "fixture.twee", VALUE_KINDS)
        artifact = mask_passage(body, source.passages[0])
        self.assertIn("C-could you take me with you?", artifact.masked_text)
        self.assertNotIn("heart.png", artifact.masked_text)
        self.assertEqual(restore_mask(artifact), source.passages[0].body_span and body[source.passages[0].body_span.start:source.passages[0].body_span.end])

    def test_widget_body_is_opaque(self) -> None:
        body = b':: Widgets [widget]\n<<widget "demo">>Hidden prose <<gagged_speech "no">><</widget>>\n:: Call\n<<demo>>Visible\n'
        source = parse_file(body, "fixture.twee", VALUE_KINDS)
        definition = source.passages[0].nodes[0]
        self.assertEqual(definition.role, "widget_definition")
        self.assertFalse(any(node.name == "gagged_speech" for node in source.passages[0].nodes))
        self.assertTrue(any(node.name == "demo" for node in source.passages[1].nodes))
        artifact = mask_passage(body, source.passages[0])
        self.assertNotIn("Hidden prose", artifact.masked_text)
        self.assertEqual(restore_mask(artifact), body[source.passages[0].body_span.start:source.passages[0].body_span.end])

    def test_unclassified_is_protected_and_logged(self) -> None:
        body = b":: Test\n<<notInSchema \"Do not expose\">>\n"
        source = parse_file(body, "fixture.twee", VALUE_KINDS)
        artifact = mask_passage(body, source.passages[0])
        self.assertNotIn("Do not expose", artifact.masked_text)
        self.assertTrue(any(item.code == "unclassified_argument" for item in artifact.diagnostics))
        self.assertEqual(restore_mask(artifact), body[source.passages[0].body_span.start:source.passages[0].body_span.end])


if __name__ == "__main__":
    unittest.main()
