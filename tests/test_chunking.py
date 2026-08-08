from __future__ import annotations

import unittest

from pretranslation_cst import mask_passage, parse_file, restore_mask
from pretranslation_cst.chunking import DEFAULT_THRESHOLD, chunk_passage
from pretranslation_cst.paths import DEFAULT_VALUE_KIND_PATH


class ChunkingTests(unittest.TestCase):
    def _chunks(self, body: bytes, **kwargs) -> object:
        source = parse_file(body, "chunk.twee", DEFAULT_VALUE_KIND_PATH)
        passage = source.passages[0]
        artifact = mask_passage(body, passage)
        return chunk_passage(passage, artifact, body, **kwargs)

    def test_small_passage_is_a_single_unit(self) -> None:
        body = b":: Test\nHello there. This is short.\n"
        units = self._chunks(body)
        self.assertEqual(len(units), 1)
        self.assertIn("Hello there", units[0].masked_text)
        self.assertEqual(units[0].char_count, len(units[0].masked_text))
        self.assertEqual(units[0].unit_count, 1)

    def test_join_units_equals_masked_text(self) -> None:
        long_body = (
            b"Intro text that is long enough to be split. "
            b"<<if $x>>Branch one <<gagged_speech 'hi'>><</if>> "
            b"<<switch $y>><<case 1>>Case one<<case 2>>Case two<</switch>> "
            b"Trailing text. "
        ) * 12
        body = b":: Test\n" + long_body + b"\n"
        source = parse_file(body, "chunk.twee", DEFAULT_VALUE_KIND_PATH)
        passage = source.passages[0]
        artifact = mask_passage(body, passage)
        units = chunk_passage(passage, artifact, body, threshold=200)
        self.assertGreater(len(units), 1)
        joined = "".join(unit.masked_text for unit in units)
        self.assertEqual(joined, artifact.masked_text)
        self.assertTrue(all(unit.char_count <= 2000 for unit in units))

    def test_placeholder_never_straddles_unit_boundary(self) -> None:
        long_body = (
            b"<<link 'Go home' 'Home'>>Home<</link>> "
            b"<<if $x>>A <<gagged_speech 'longer piece of dialogue here'>> B<</if>> "
        ) * 10
        body = b":: Test\n" + long_body + b"\n"
        source = parse_file(body, "chunk.twee", DEFAULT_VALUE_KIND_PATH)
        passage = source.passages[0]
        artifact = mask_passage(body, passage)
        units = chunk_passage(passage, artifact, body, threshold=150)
        self.assertGreater(len(units), 1)
        for unit in units:
            for placeholder in unit.placeholders:
                self.assertIn(placeholder.placeholder, unit.masked_text)

    def test_ancestors_are_present_for_branch_units(self) -> None:
        long_body = (
            b"<<if $x>>This is the if branch. "
            b"<<print 'more text'>> and more here to force a split.<</if>> "
        ) * 8
        body = b":: Test\n" + long_body + b"\n"
        source = parse_file(body, "chunk.twee", DEFAULT_VALUE_KIND_PATH)
        passage = source.passages[0]
        artifact = mask_passage(body, passage)
        units = chunk_passage(passage, artifact, body, threshold=200)
        self.assertGreater(len(units), 1)
        container_units = [u for u in units if u.ancestors]
        self.assertTrue(container_units)
        for unit in container_units:
            self.assertTrue(any(a["node_type"] == "macro_container" for a in unit.ancestors))

    def test_restore_of_chunked_and_translated_text(self) -> None:
        long_body = (
            b"<<if $x>>A longer branch sentence that gets split. "
            b"<<gagged_speech 'yelled dialogue'>> and tail<</if>> "
        ) * 9
        body = b":: Test\n" + long_body + b"\n"
        source = parse_file(body, "chunk.twee", DEFAULT_VALUE_KIND_PATH)
        passage = source.passages[0]
        artifact = mask_passage(body, passage)
        units = chunk_passage(passage, artifact, body, threshold=200)
        # simulate translation: concatenate units, then restore placeholders
        joined = "".join(unit.masked_text for unit in units)
        rebuilt = joined
        for placeholder in artifact.placeholders:
            rebuilt = rebuilt.replace(placeholder.placeholder, placeholder.original_text, 1)
        self.assertEqual(rebuilt.encode("utf-8"), body[passage.body_span.start:passage.body_span.end])

    def test_opaque_passage_has_no_units(self) -> None:
        body = b":: StoryData\n{\"ifid\":\"x\"}\n"
        source = parse_file(body, "opaque.twee", DEFAULT_VALUE_KIND_PATH)
        passage = source.passages[0]
        artifact = mask_passage(body, passage)
        units = chunk_passage(passage, artifact, body)
        self.assertEqual(units, [])

    def test_small_units_merge_only_within_same_context(self) -> None:
        # Structure-aware minimal merge (F9): a tiny content unit merges
        # with the next unit only when both share the same ancestor path —
        # a tiny container must NOT merge into the following container's
        # unit (which would couple unrelated text into one reuse key).
        body = (
            b":: Test\n"
            + (b"<<if $x>>tiny<</if>> <<switch $y>><<case 1>>also small"
               b"<</switch>> ") * 8
            + b"\n"
        )
        source = parse_file(body, "chunk.twee", DEFAULT_VALUE_KIND_PATH)
        passage = source.passages[0]
        artifact = mask_passage(body, passage)
        units = chunk_passage(passage, artifact, body, threshold=200, min_chars=200)
        for unit in units:
            if not unit.placeholders:
                continue
            names = set()
            for ph in unit.placeholders:
                text = ph.original_text
                if "if" in text:
                    names.add("if")
                if "switch" in text:
                    names.add("switch")
            self.assertLessEqual(len(names), 1, unit.masked_text)
        joined = "".join(unit.masked_text for unit in units)
        self.assertEqual(joined, artifact.masked_text)

    def test_tiny_slivers_merge_into_neighbour(self) -> None:
        # "The " (5 chars, same branch) must merge into the next unit — a
        # standalone sliver would otherwise be translated badly or dropped
        # entirely (observed: "The " -> "\t")
        body = (
            b":: Test\n<<if $x>>"
            + (b"The <<print 'word'>> is wide. " * 14)
            + b"more trailing text here<</if>>\n"
        )
        source = parse_file(body, "chunk.twee", DEFAULT_VALUE_KIND_PATH)
        passage = source.passages[0]
        artifact = mask_passage(body, passage)
        units = chunk_passage(passage, artifact, body, threshold=300, min_chars=100)
        self.assertGreater(len(units), 1)
        for unit in units:
            self.assertNotEqual(unit.masked_text.strip(), "The")
        joined = "".join(unit.masked_text for unit in units)
        self.assertEqual(joined, artifact.masked_text)


if __name__ == "__main__":
    unittest.main()