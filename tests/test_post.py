from __future__ import annotations

import unittest

from translation.post import (
    get_post_num,
    normalize_markers,
    post_process,
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

    def test_slash_form(self) -> None:
        text = "로빈이/가 재채기를 했습니다."
        out = normalize_markers(text)
        self.assertIn("{{post:이가}}", out)

    def test_ida_form(self) -> None:
        text = "그건 사실이(다)."
        out = normalize_markers(text)
        self.assertIn("{{post:이다}}", out)

    def test_invariant_particles(self) -> None:
        self.assertEqual(resolve_static("사진{{post:의}} 가치"), "사진의 가치")
        self.assertEqual(resolve_static("서울{{post:에서}} 왔다"), "서울에서 왔다")
        self.assertEqual(resolve_static("빵{{post:도}} 주세요"), "빵도 주세요")

    def test_marker_name_not_nested(self) -> None:
        text = "로빈{{post:이/가}} 재채기를 했습니다."
        out = normalize_markers(text)
        self.assertIn("{{post:이가}}", out)
        self.assertNotIn("{{post:{{post:", out)

    def test_reversed_pairs(self) -> None:
        self.assertIn("{{post:을를}}", normalize_markers("밥를(을) 먹었다"))
        self.assertIn("{{post:이가}}", normalize_markers("로빈가(이) 웃었다"))
        self.assertIn("{{post:으로로}}", normalize_markers("학교로(으)로 간다"))
        self.assertIn("{{post:의}}", normalize_markers("사진의(의) 가치"))


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

    def test_static_euro_jongseong(self) -> None:
        text = "밥{{post:으로로}} 먹었다."
        out = resolve_static(text)
        self.assertIn("밥으로", out)

    def test_static_euro_no_jongseong(self) -> None:
        text = "학교{{post:으로로}} 간다."
        out = resolve_static(text)
        self.assertIn("학교로", out)

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

    def test_unknown_marker_kept(self) -> None:
        text = "사진{{post:이라든지}} 가치"
        out = resolve_static(text)
        self.assertIn("{{post:이라든지}}", out)


class PostProcessTests(unittest.TestCase):
    def test_full_pipeline_static(self) -> None:
        text = "오션 브리즈 카페은(는) 붐빈다. 빵을(를) 먹었다."
        out = post_process(text)
        self.assertIn("카페는", out)
        self.assertIn("빵을", out)
        self.assertNotIn("(", out)
        self.assertNotIn("{{post:", out)

    def test_full_pipeline_dynamic_stays(self) -> None:
        text = "<000031>이(가) 말했다."
        out = post_process(text)
        self.assertIn("<000031>{{post:이가}}", out)
        self.assertEqual(remaining_dynamic_markers(out), ["이가"])

    def test_placeholder_untouched(self) -> None:
        text = "<000031>이(가) <000032>을(를) 치려고."
        out = post_process(text)
        self.assertIn("<000031>", out)
        self.assertIn("<000032>", out)


if __name__ == "__main__":
    unittest.main()