from __future__ import annotations

import unittest

from pretranslation_cst import mask_passage, parse_file, restore_mask
from pretranslation_cst.paths import DEFAULT_VALUE_KIND_PATH
from pretranslation_cst.square_markup import (
    DYNAMIC_LABEL_MARKERS,
    exposed_label,
    parse_square_markup,
)

VALUE_KINDS = DEFAULT_VALUE_KIND_PATH


def parse(markup: str) -> tuple[object, object]:
    return parse_square_markup(markup, 0, len(markup)), markup


class SquareMarkupUnitTests(unittest.TestCase):
    def test_pipe_delimiter_positions_label_and_target(self) -> None:
        result = parse_square_markup("[[label|target]]", 0, 16)
        self.assertTrue(result.ok)
        self.assertTrue(result.is_link)
        self.assertFalse(result.is_image)
        self.assertEqual((result.text.start, result.text.end, result.text.text), (2, 7, "label"))
        self.assertEqual((result.link.start, result.link.end, result.link.text), (8, 14, "target"))
        self.assertIsNone(result.setter)

    def test_right_arrow_delimiter_positions_label_and_target(self) -> None:
        result = parse_square_markup("[[label->target]]", 0, 17)
        self.assertTrue(result.ok)
        self.assertTrue(result.is_link)
        self.assertEqual((result.text.start, result.text.end, result.text.text), (2, 7, "label"))
        self.assertEqual((result.link.start, result.link.end, result.link.text), (9, 15, "target"))

    def test_left_arrow_delimiter_swaps_label_and_target_sides(self) -> None:
        result = parse_square_markup("[[target<-label]]", 0, 17)
        self.assertTrue(result.ok)
        self.assertTrue(result.is_link)
        self.assertEqual((result.link.start, result.link.end, result.link.text), (2, 8, "target"))
        self.assertEqual((result.text.start, result.text.end, result.text.text), (10, 15, "label"))

    def test_no_delimiter_has_no_separate_label(self) -> None:
        result = parse_square_markup("[[target]]", 0, 10)
        self.assertTrue(result.ok)
        self.assertTrue(result.is_link)
        self.assertEqual((result.link.start, result.link.end, result.link.text), (2, 8, "target"))
        self.assertIsNone(result.text)

    def test_setter_span_is_preserved(self) -> None:
        result = parse_square_markup("[[label|target][$var to 1]]", 0, 27)
        self.assertTrue(result.ok)
        self.assertEqual((result.text.start, result.text.end), (2, 7))
        self.assertEqual((result.link.start, result.link.end), (8, 14))
        self.assertEqual((result.setter.start, result.setter.end, result.setter.text), (16, 25, "$var to 1"))

    def test_setter_without_label_delimiter(self) -> None:
        result = parse_square_markup("[[target][$var to 1]]", 0, 21)
        self.assertTrue(result.ok)
        self.assertIsNone(result.text)
        self.assertEqual((result.link.start, result.link.end, result.link.text), (2, 8, "target"))
        self.assertEqual((result.setter.start, result.setter.end, result.setter.text), (10, 19, "$var to 1"))

    def test_nested_square_markup_is_counted_in_depth(self) -> None:
        result = parse_square_markup("[[a [[b]] c|target]]", 0, 20)
        self.assertTrue(result.ok)
        self.assertEqual((result.text.start, result.text.end, result.text.text), (2, 11, "a [[b]] c"))
        self.assertEqual((result.link.start, result.link.end, result.link.text), (12, 18, "target"))

    def test_quote_slurps_delimiters_inside_label(self) -> None:
        result = parse_square_markup('[[a "b|c" d|target]]', 0, 20)
        self.assertTrue(result.ok)
        self.assertEqual((result.text.start, result.text.end, result.text.text), (2, 11, 'a "b|c" d'))
        self.assertEqual((result.link.start, result.link.end, result.link.text), (12, 18, "target"))

    def test_backslash_is_not_a_delimiter_escape(self) -> None:
        result = parse_square_markup(r"[[a\|b|c]]", 0, 10)
        self.assertTrue(result.ok)
        self.assertEqual((result.text.start, result.text.end, result.text.text), (2, 4, "a\\"))
        self.assertEqual((result.link.start, result.link.end, result.link.text), (5, 8, "b|c"))

    def test_arrow_inside_target_is_content_after_first_delimiter(self) -> None:
        result = parse_square_markup("[[a|b->c]]", 0, 10)
        self.assertTrue(result.ok)
        self.assertEqual(result.text.text, "a")
        self.assertEqual(result.link.text, "b->c")

    def test_early_arrow_wins_over_later_pipe(self) -> None:
        result = parse_square_markup("[[a->b|c]]", 0, 10)
        self.assertTrue(result.ok)
        self.assertEqual(result.text.text, "a")
        self.assertEqual(result.link.text, "b|c")

    def test_unterminated_quote_is_an_error(self) -> None:
        result = parse_square_markup('[[a "b]]', 0, 8)
        self.assertFalse(result.ok)
        self.assertIn("unterminated double quoted string", result.error)

    def test_unexpected_close_is_malformed(self) -> None:
        result = parse_square_markup("[[a]b]]", 0, 7)
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "malformed link markup")

    def test_image_markup_is_distinguished_from_links(self) -> None:
        result = parse_square_markup("[img[src]]", 0, 10)
        self.assertTrue(result.ok)
        self.assertFalse(result.is_link)
        self.assertTrue(result.is_image)
        self.assertIsNone(result.text)
        self.assertEqual((result.source.start, result.source.end, result.source.text), (5, 8, "src"))

    def test_image_alignment_left_and_right(self) -> None:
        left = parse_square_markup("[<img[src]]", 0, 11)
        self.assertTrue(left.ok)
        self.assertTrue(left.is_image)
        self.assertEqual(left.align, "left")
        right = parse_square_markup("[>img[src]]", 0, 11)
        self.assertTrue(right.ok)
        self.assertTrue(right.is_image)
        self.assertEqual(right.align, "right")

    def test_image_pipe_is_alt_text_before_source(self) -> None:
        result = parse_square_markup("[img[a|b]]", 0, 10)
        self.assertTrue(result.ok)
        self.assertEqual((result.text.start, result.text.end, result.text.text), (5, 6, "a"))
        self.assertEqual((result.source.start, result.source.end, result.source.text), (7, 8, "b"))

    def test_image_link_component_after_inner_meta(self) -> None:
        result = parse_square_markup("[img[src][link]]", 0, 16)
        self.assertTrue(result.ok)
        self.assertEqual((result.source.start, result.source.end, result.source.text), (5, 8, "src"))
        self.assertEqual((result.link.start, result.link.end, result.link.text), (10, 14, "link"))

    def test_tilde_force_internal_marker_is_recorded(self) -> None:
        result = parse_square_markup("[[~target]]", 0, 11)
        self.assertTrue(result.ok)
        self.assertTrue(result.force_internal)
        self.assertEqual(result.link.text, "~target")

    def test_malformed_aligner_is_an_error(self) -> None:
        result = parse_square_markup("[<>img[src]]", 0, 12)
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "malformed square-bracketed markup")


class ExposedLabelTests(unittest.TestCase):
    def test_static_pipe_label_is_exposed(self) -> None:
        result = parse_square_markup("[[Plain label|Target]]", 0, 22)
        part = exposed_label(result)
        self.assertIsNotNone(part)
        self.assertEqual(part.text, "Plain label")

    def test_static_arrow_labels_are_exposed(self) -> None:
        right = parse_square_markup("[[Finish up->Bath Finish]]", 0, 26)
        self.assertEqual(exposed_label(right).text, "Finish up")
        left = parse_square_markup("[[Passout home<-Fade to black...]]", 0, 34)
        self.assertEqual(exposed_label(left).text, "Fade to black...")

    def test_no_delimiter_label_is_not_exposed(self) -> None:
        result = parse_square_markup("[[Target]]", 0, 10)
        self.assertIsNone(exposed_label(result))

    def test_dynamic_markers_are_not_exposed(self) -> None:
        cases = [
            "[[$name|Target]]",
            "[[_label|Target]]",
            "[[`expr`|Target]]",
            "[[${name}|Target]]",
            "[[first + last|Target]]",
            "[[Prefix $var|Target]]",
        ]
        for markup in cases:
            result = parse_square_markup(markup, 0, len(markup))
            self.assertIsNone(exposed_label(result), markup)

    def test_image_alt_text_is_not_a_link_label(self) -> None:
        result = parse_square_markup("[img[alt|src]]", 0, 12)
        self.assertIsNone(exposed_label(result))

    def test_empty_label_is_not_exposed(self) -> None:
        result = parse_square_markup("[[|Target]]", 0, 11)
        self.assertIsNone(exposed_label(result))

    def test_setter_link_label_is_still_exposed(self) -> None:
        markup = "[[Next|Tutorial Finish][$seen to true]]"
        result = parse_square_markup(markup, 0, len(markup))
        self.assertEqual(exposed_label(result).text, "Next")

    def test_dynamic_marker_set_covers_documented_markers(self) -> None:
        self.assertIn("$", DYNAMIC_LABEL_MARKERS)
        self.assertIn("_", DYNAMIC_LABEL_MARKERS)
        self.assertIn("`", DYNAMIC_LABEL_MARKERS)
        self.assertIn("${", DYNAMIC_LABEL_MARKERS)
        self.assertIn("+", DYNAMIC_LABEL_MARKERS)


class SquareMarkupParserWiringTests(unittest.TestCase):
    def _passage(self, body: bytes, name: str = "Links") -> object:
        source = parse_file(body, "square.twee", VALUE_KINDS)
        return source.passages[0]

    def test_standalone_and_macro_argument_share_the_label_span(self) -> None:
        body = b":: Links\n[[Next|Tutorial Finish]]\n<<link [[Next|Tutorial Finish]]>><</link>>\n"
        passage = self._passage(body)
        labels = [span for span, kind in passage.exposed_candidates if kind == "link_label"]
        self.assertEqual(len(labels), 2)
        standalone, macro = labels
        self.assertEqual(body[standalone.start:standalone.end], b"Next")
        self.assertEqual(body[macro.start:macro.end], b"Next")

    def test_square_opener_requires_exact_img_spelling(self) -> None:
        body = b":: Links\n[Mg[src]] [G[src]] [Igno]] [[Real link|Target]]\n"
        passage = self._passage(body)
        labels = [span for span, kind in passage.exposed_candidates if kind == "link_label"]
        self.assertEqual(len(labels), 1)
        self.assertEqual(body[labels[0].start:labels[0].end], b"Real link")
        artifact = mask_passage(body, passage)
        self.assertIn("Real link", artifact.masked_text)
        self.assertEqual(restore_mask(artifact), body[passage.body_span.start:passage.body_span.end])

    def test_left_arrow_standalone_exposes_the_label_after_the_arrow(self) -> None:
        body = b":: Links\n[[Passout home<-Everything fades to black...]]\n"
        passage = self._passage(body)
        labels = [span for span, kind in passage.exposed_candidates if kind == "link_label"]
        self.assertEqual(len(labels), 1)
        self.assertEqual(body[labels[0].start:labels[0].end], b"Everything fades to black...")

    def test_dynamic_labels_are_never_exposed(self) -> None:
        body = (
            b":: Links\n"
            b"[[$name|Target]]\n"
            b"[[_label|Target]]\n"
            b"[[`expr`|Target]]\n"
            b"[[first + last|Target]]\n"
            b'[["Have a bath " + _clothed + "(0:30)"->Bath]]\n'
        )
        passage = self._passage(body)
        self.assertFalse([span for span, kind in passage.exposed_candidates if kind == "link_label"])
        artifact = mask_passage(body, passage)
        self.assertNotIn("$name", artifact.masked_text)
        self.assertNotIn("_label", artifact.masked_text)
        self.assertNotIn("first + last", artifact.masked_text)

    def test_multibyte_label_keeps_byte_exact_spans(self) -> None:
        body = ":: Links\n[[안녕하세요|다음]]\n".encode("utf-8")
        passage = self._passage(body)
        labels = [span for span, kind in passage.exposed_candidates if kind == "link_label"]
        self.assertEqual(len(labels), 1)
        self.assertEqual(body[labels[0].start:labels[0].end], "안녕하세요".encode("utf-8"))
        artifact = mask_passage(body, passage)
        self.assertIn("안녕하세요", artifact.masked_text)
        from pretranslation_cst import restore_mask

        self.assertEqual(restore_mask(artifact), body[passage.body_span.start:passage.body_span.end])

    def test_standalone_image_markup_is_protected(self) -> None:
        from pretranslation_cst import restore_mask

        body = b":: Links\n[img[src.png]]\n"
        passage = self._passage(body)
        self.assertFalse([span for span, kind in passage.exposed_candidates if kind == "link_label"])
        artifact = mask_passage(body, passage)
        self.assertNotIn("src.png", artifact.masked_text)
        self.assertEqual(restore_mask(artifact), body[passage.body_span.start:passage.body_span.end])

    def test_image_macro_argument_is_protected_without_link_label(self) -> None:
        from pretranslation_cst import restore_mask

        body = b':: Links\n<<link [img[src.png]]>><</link>>\n'
        passage = self._passage(body)
        self.assertFalse([span for span, kind in passage.exposed_candidates if kind == "link_label"])
        artifact = mask_passage(body, passage)
        self.assertNotIn("src.png", artifact.masked_text)
        self.assertEqual(restore_mask(artifact), body[passage.body_span.start:passage.body_span.end])

    def test_string_form_link_static_label_is_exposed(self) -> None:
        body = b':: Links\n<<link "Control Up" "statDisplay Test">><</link>>\n'
        passage = self._passage(body)
        labels = [span for span, kind in passage.exposed_candidates if kind == "link_label"]
        self.assertEqual(len(labels), 1)
        self.assertEqual(body[labels[0].start:labels[0].end], b"Control Up")
        artifact = mask_passage(body, passage)
        self.assertIn("Control Up", artifact.masked_text)
        self.assertTrue(any(segment.kind == "link_label" and segment.text == "Control Up" for segment in artifact.segments))
        self.assertNotIn("statDisplay Test", artifact.masked_text)
        self.assertEqual(restore_mask(artifact), body[passage.body_span.start:passage.body_span.end])

    def test_string_form_link_dynamic_label_is_protected(self) -> None:
        body = b':: Links\n<<link "Hello " + $name "Target">><</link>>\n'
        passage = self._passage(body)
        # Raw expression macro arg[0] for link is not a string literal; lexer
        # would not classify it as "string" lexeme_kind. This test pins that a
        # string literal with a dynamic marker is also protected.
        body2 = b':: Links\n<<link "$name" "Target">><</link>>\n'
        passage2 = self._passage(body2)
        labels = [span for span, kind in passage2.exposed_candidates if kind == "link_label"]
        self.assertFalse(labels)
        artifact = mask_passage(body2, passage2)
        self.assertNotIn("$name", artifact.masked_text)

    def test_arrow_macro_argument_matches_standalone_parser(self) -> None:
        body = b':: Links\n[[Finish up->Bath Finish]]\n<<link [[Finish up->Bath Finish]]>><</link>>\n'
        passage = self._passage(body)
        labels = [span for span, kind in passage.exposed_candidates if kind == "link_label"]
        self.assertEqual(len(labels), 2)
        self.assertEqual(body[labels[0].start:labels[0].end], b"Finish up")
        self.assertEqual(body[labels[1].start:labels[1].end], b"Finish up")

    def test_malformed_arrow_content_is_not_exposed(self) -> None:
        body = b":: Links\n[[a]b]]\n"
        passage = self._passage(body)
        self.assertFalse([span for span, kind in passage.exposed_candidates if kind == "link_label"])
        artifact = mask_passage(body, passage)
        self.assertNotIn("a]b", artifact.masked_text)

    def test_label_parent_lookup_works_through_macro_tree(self) -> None:
        body = b':: Links\n<<link [[Next|Tutorial Finish]]>><</link>>\n'
        passage = self._passage(body)
        link = next(node for node in passage.nodes if node.name == "link")
        markup = next(child for child in link.children if child.node_type == "protected_markup")
        label = next(child for child in markup.children if child.node_type == "prose_text")
        self.assertEqual(label.name, "link_label")
        self.assertIn(link, passage.get_ancestors(label.node_id))


if __name__ == "__main__":
    unittest.main()
