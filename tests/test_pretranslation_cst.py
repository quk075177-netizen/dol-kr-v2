from __future__ import annotations

import json
import unittest

from pretranslation_cst import mask_passage, parse_file, restore_mask, split_twee
from pretranslation_cst.paths import DEFAULT_VALUE_KIND_PATH


VALUE_KINDS = DEFAULT_VALUE_KIND_PATH


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
        self.assertEqual(body[calls[1].span.start:calls[1].span.end], b"<<if $x >> 5>>Hi<</if>>")

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

    def test_special_passage_body_is_opaque(self) -> None:
        body = (
            b":: StoryData\n{\"ifid\":\"x\",\"fake\":\"<<gagged_speech 'no'>>\"}\n"
            b":: StoryInit\n<<gagged_speech 'also hidden'>>\n"
            b":: StoryMenu\n<<gagged_speech 'menu hidden'>>\n"
            b":: Normal\nVisible\n"
        )
        source = parse_file(body, "special.twee", VALUE_KINDS)
        self.assertEqual([item.name for item in source.passages], ["StoryData", "StoryInit", "StoryMenu", "Normal"])
        for passage in source.passages[:3]:
            self.assertTrue(passage.is_opaque)
            self.assertFalse(passage.nodes)
            self.assertEqual(restore_mask(mask_passage(body, passage)), body[passage.body_span.start:passage.body_span.end])

    def test_script_and_stylesheet_tags_are_opaque(self) -> None:
        body = b":: Code [script]\nconst fake = '<<gagged_speech \\\"no\\\">>';\n:: CSS [stylesheet]\n.foo { content: '<<if>>'; }\n"
        source = parse_file(body, "code.twee", VALUE_KINDS)
        self.assertEqual([passage.tags for passage in source.passages], [["script"], ["stylesheet"]])
        self.assertTrue(all(passage.is_opaque for passage in source.passages))

    def test_literal_and_dynamic_link_labels(self) -> None:
        body = b":: Links\n[[Plain label|Target]] [[Dynamic $name|Target]]\n"
        source = parse_file(body, "links.twee", VALUE_KINDS)
        artifact = mask_passage(body, source.passages[0])
        self.assertIn("Plain label", artifact.masked_text)
        self.assertNotIn("Dynamic $name", artifact.masked_text)
        self.assertEqual(restore_mask(artifact), body[source.passages[0].body_span.start:source.passages[0].body_span.end])

    def test_nested_widget_only_outer_definition_is_recorded(self) -> None:
        body = b':: Widgets [widget]\n<<widget "outer">>outer <<widget "inner">>inner<</widget>> end<</widget>>\n:: Call\n<<outer>>shown\n'
        source = parse_file(body, "nested.twee", VALUE_KINDS)
        definitions = [node for node in source.passages[0].nodes if node.role == "widget_definition"]
        self.assertEqual(len(definitions), 1)
        self.assertFalse(any(node.name == "inner" for node in source.passages[0].nodes))
        self.assertEqual([node.name for node in source.passages[1].nodes], ["outer"])

    def test_bom_is_prefix_and_counts_in_byte_offsets(self) -> None:
        body = b"\xef\xbb\xbf:: Test\n\xea\xb0\x80\n"
        source = split_twee(body, "bom.twee")
        passage = source.passages[0]
        self.assertEqual(body[source.prefix_span.start:source.prefix_span.end], b"\xef\xbb\xbf")
        self.assertEqual(passage.header_span.start, 3)
        self.assertEqual(body[passage.body_span.start:passage.body_span.end], "가\n".encode())

    def test_tree_parent_and_sibling_queries(self) -> None:
        body = b':: Test\n<<if $x>>A<<print "one">><<else>>B<<print "two">><</if>>\n'
        source = parse_file(body, "tree.twee", VALUE_KINDS)
        passage = source.passages[0]
        self.assertIsNotNone(passage.root)
        container = next(node for node in passage.nodes if node.name == "if")
        self.assertEqual(container.node_type, "macro_container")
        self.assertTrue(any(child.node_type == "macro_branch" for child in container.children))
        branch = next(child for child in container.children if child.node_type == "macro_branch")
        self.assertIn(container, passage.get_ancestors(branch.children[0].node_id))
        self.assertEqual(branch.children[0].sibling_order, 0)
        self.assertEqual(passage.get_siblings(branch.children[0].node_id), branch.children[1:])

    def test_malformed_macro_is_protected_until_passage_end(self) -> None:
        body = b':: Broken\n<<set $x to "unterminated\nVisible-looking prose\n'
        source = parse_file(body, "broken.twee", VALUE_KINDS)
        artifact = mask_passage(body, source.passages[0])
        self.assertTrue(any(item.code == "malformed_macro" for item in artifact.diagnostics))
        self.assertNotIn("Visible-looking prose", artifact.masked_text)
        self.assertEqual(restore_mask(artifact), body[source.passages[0].body_span.start:source.passages[0].body_span.end])

    def test_square_and_regex_arguments_keep_their_boundaries(self) -> None:
        body = b':: Tokens\n<<link [[text|target]]>>ok<</link>> <<print /a[>]b\\/c/>>\n'
        source = parse_file(body, "tokens.twee", VALUE_KINDS)
        names = [node.name for node in source.passages[0].nodes if node.role == "call"]
        self.assertEqual(names, ["link", "/link", "print"])
        print_node = next(node for node in source.passages[0].nodes if node.name == "print")
        self.assertEqual(print_node.arg_mode, "raw")
        self.assertFalse(print_node.args)
        self.assertEqual(
            body[print_node.expression_span.start:print_node.expression_span.end],
            b"/a[>]b\\/c/",
        )

    def test_skip_args_macros_keep_one_raw_expression_span(self) -> None:
        body = (
            b':: Expressions\n'
            b'<<set _anusaction["Straddle " + $NPCList[0].penisdesc] to "anustopenisdouble">>\n'
            b'<<print _full.join(" and ")>>\n'
            b'<<if $a and $b>>yes<</if>>\n'
        )
        source = parse_file(body, "expressions.twee", VALUE_KINDS)
        passage = source.passages[0]
        for name in ("set", "print", "if"):
            node = next(item for item in passage.nodes if item.name == name)
            self.assertEqual(node.arg_mode, "raw")
            self.assertFalse(node.args)
            self.assertIsNotNone(node.expression_span)
        self.assertFalse(any(item.code == "malformed_args" for item in passage.diagnostics))
        self.assertFalse(any(
            item.code == "unclassified_argument" and item.macro_name in {"set", "print", "if"}
            for item in passage.diagnostics
        ))

    def test_division_is_not_scanned_as_a_regex_literal(self) -> None:
        body = b':: Division\n<<if 3/7 lt 1>>yes<</if>> <<print /a[>]b\\/c/>>\n'
        source = parse_file(body, "division.twee", VALUE_KINDS)
        passage = source.passages[0]
        self.assertEqual([node.name for node in passage.nodes], ["if", "/if", "print"])
        container = passage.nodes[0]
        self.assertEqual(body[container.span.start:container.span.end], b"<<if 3/7 lt 1>>yes<</if>>")
        self.assertFalse(any(item.code == "malformed_macro" for item in passage.diagnostics))

    def test_registry_distinguishes_containers_from_leaf_controls(self) -> None:
        body = (
            b':: Registry\n'
            b'<<addinlineevent "event">>Event prose<</addinlineevent>>\n'
            b'<<foldout false "_fold">>Fold prose<</foldout>>\n'
            b'<<linkreplace "Open">>Replacement prose<</linkreplace>>\n'
            b'<<radiobutton "$radio" "value">>Radio prose\n'
            b'<<checkbox "$check" 0 1>>Checkbox prose\n'
        )
        source = parse_file(body, "registry.twee", VALUE_KINDS)
        passage = source.passages[0]
        by_name = {node.name: node for node in passage.nodes if not node.name.startswith("/")}
        for name in ("addinlineevent", "foldout", "linkreplace"):
            self.assertEqual(by_name[name].node_type, "macro_container")
        for name in ("radiobutton", "checkbox"):
            self.assertEqual(by_name[name].node_type, "macro_call")
        self.assertFalse(any(item.code in {"mismatched_close", "unclosed_container"} for item in passage.diagnostics))
        artifact = mask_passage(body, passage)
        self.assertIn("Radio prose", artifact.masked_text)
        self.assertIn("Checkbox prose", artifact.masked_text)

    def test_link_macro_square_label_is_a_cst_exposed_leaf(self) -> None:
        body = b':: Links\n<<link [[Next|Tutorial Finish]]>><</link>>\n'
        source = parse_file(body, "link-macro.twee", VALUE_KINDS)
        passage = source.passages[0]
        link = next(node for node in passage.nodes if node.name == "link")
        markup = next(child for child in link.children if child.node_type == "protected_markup")
        label = next(child for child in markup.children if child.node_type == "prose_text")
        self.assertEqual(label.name, "link_label")
        self.assertIn(link, passage.get_ancestors(label.node_id))
        artifact = mask_passage(body, passage)
        self.assertIn("Next", artifact.masked_text)
        self.assertTrue(any(segment.kind == "link_label" for segment in artifact.segments))
        self.assertEqual(restore_mask(artifact), body[passage.body_span.start:passage.body_span.end])

    def test_square_label_exposure_is_limited_by_macro_grammar(self) -> None:
        body = b':: Square\n<<include [[Not a display label|Target]]>>\n'
        source = parse_file(body, "square-structural.twee", VALUE_KINDS)
        artifact = mask_passage(body, source.passages[0])
        self.assertNotIn("Not a display label", artifact.masked_text)
        self.assertFalse(any(segment.kind == "link_label" for segment in artifact.segments))


if __name__ == "__main__":
    unittest.main()
