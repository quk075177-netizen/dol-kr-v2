from __future__ import annotations

import unittest

from translation.post import (
    get_post_num,
    normalize_markers,
    remaining_dynamic_markers,
    resolve_static,
)


class PostNumTests(unittest.TestCase):
    def test_hangul_jongseong(self) -> None:
        self.assertEqual(get_post_num("밥"), 0)     # ㅂ 받침
        self.assertEqual(get_post_num("학교"), 1)   # 받침X
        self.assertEqual(get_post_num("서울"), 2)   # ㄹ 받침

    def test_digits(self) -> None:
        # [0,2,1,0,1,1,0,2,2,0]: 0→0, 1→2, 2→1, 3→0, 4→1, 5→1, 6→0, 7→2, 8→2, 9→0
        self.assertEqual(get_post_num("0"), 0)
        self.assertEqual(get_post_num("1"), 2)
        self.assertEqual(get_post_num("2"), 1)
        self.assertEqual(get_post_num("3"), 0)
        self.assertEqual(get_post_num("7"), 2)
        self.assertEqual(get_post_num("9"), 0)

    def test_latin_and_empty(self) -> None:
        self.assertIsNone(get_post_num("Robin"))
        self.assertIsNone(get_post_num(""))
        self.assertIsNone(get_post_num("(0:02)"))


class NormalizeTests(unittest.TestCase):
    def test_adhoc_markers(self) -> None:
        text = "{{name}}이(가) {{body}}을(를) {{tool}}으로(로) 치려고"
        out = normalize_markers(text)
        self.assertIn("{{post:이가}}", out)
        self.assertIn("{{post:을를}}", out)
        self.assertIn("{{post:으로로}}", out)
        self.assertNotIn("이(가)", out)

    def test_legacy_markers(self) -> None:
        text = "당신의 $worn.upper.name【은는】 드러내고 있습니다."
        out = normalize_markers(text)
        self.assertIn("{{post:은는}}", out)
        self.assertNotIn("【은는】", out)

    def test_double_paren_forms(self) -> None:
        text = "빵(을)를"  # unusual, not matched → stays
        out = normalize_markers(text)
        self.assertEqual(out, text)


class ResolveStaticTests(unittest.TestCase):
    def test_static_hangul(self) -> None:
        text = "오션 브리즈 카페{{post:은는}} 붐빈다."
        out = resolve_static(text)
        self.assertIn("카페는", out)
        self.assertNotIn("{{post:", out)

    def test_static_with_jongseong(self) -> None:
        text = "빵{{post:을를}} 먹었다."
        out = resolve_static(text)
        self.assertIn("빵을", out)

    def test_static_rieul(self) -> None:
        text = "서울{{post:으로로}} 간다."
        out = resolve_static(text)
        self.assertIn("서울로", out)

    def test_dynamic_stays(self) -> None:
        text = "$worn.upper.name{{post:은는}} 드러내고"
        out = resolve_static(text)
        self.assertIn("{{post:은는}}", out)

    def test_dynamic_macro_stays(self) -> None:
        text = "<<he 'Robin'>>{{post:이가}} 말했다"
        out = resolve_static(text)
        self.assertIn("{{post:이가}}", out)
        self.assertEqual(remaining_dynamic_markers(out), ["이가"])

    def test_leading_marker_stays(self) -> None:
        text = "{{post:은는}} 시작"
        out = resolve_static(text)
        self.assertIn("{{post:은는}}", out)


if __name__ == "__main__":
    unittest.main()