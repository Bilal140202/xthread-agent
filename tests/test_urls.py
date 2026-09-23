"""Tests: input URL normalization & validation."""
import unittest

from _loader import load_tool

m = load_tool()


class TestNormalizeInput(unittest.TestCase):
    def ok(self, inp, want_id):
        info = m.normalize_input(inp)
        self.assertEqual(info["status_id"], want_id)
        self.assertTrue(info["canonical_url"].endswith(f"/status/{want_id}"))

    def reject(self, inp):
        with self.assertRaises(m.InputError):
            m.normalize_input(inp)

    # --- accepted forms ---------------------------------------------------
    def test_x_com_status(self):
        self.ok("https://x.com/fixtureuser/status/1000000000000000001",
                "1000000000000000001")

    def test_twitter_com_status(self):
        self.ok("https://twitter.com/fixtureuser/status/1000000000000000001",
                "1000000000000000001")

    def test_statuses_path(self):
        self.ok("https://x.com/fixtureuser/statuses/1000000000000000001",
                "1000000000000000001")

    def test_mobile_host(self):
        self.ok("https://mobile.x.com/fixtureuser/status/1000000000000000001",
                "1000000000000000001")

    def test_www_host(self):
        self.ok("https://www.twitter.com/fixtureuser/status/1000000000000000001",
                "1000000000000000001")

    def test_scheme_less_input(self):
        self.ok("x.com/fixtureuser/status/1000000000000000001",
                "1000000000000000001")

    def test_i_web_status(self):
        self.ok("https://x.com/i/web/status/1000000000000000001",
                "1000000000000000001")

    def test_photo_suffix(self):
        self.ok("https://x.com/fixtureuser/status/1000000000000000001/photo/1",
                "1000000000000000001")

    def test_video_suffix(self):
        self.ok("https://x.com/fixtureuser/status/1000000000000000001/video/1",
                "1000000000000000001")

    def test_query_string_and_trailing_slash(self):
        self.ok("https://x.com/fixtureuser/status/1000000000000000001/?s=20&t=x",
                "1000000000000000001")

    def test_bare_id(self):
        self.ok("1000000000000000001", "1000000000000000001")

    def test_short_legacy_id_in_url(self):
        # historical short IDs must not be rejected in URL form
        self.ok("https://x.com/jack/status/20", "20")

    def test_whitespace_trimmed(self):
        self.ok("  https://x.com/u/status/1000000000000000001  ",
                "1000000000000000001")

    # --- rejected forms ---------------------------------------------------
    def test_empty(self):
        self.reject("")
        self.reject("   ")

    def test_profile_url(self):
        self.reject("https://x.com/fixtureuser")

    def test_hashtag_url(self):
        self.reject("https://x.com/hashtag/fixture")

    def test_search_url(self):
        self.reject("https://x.com/search?q=fixture")

    def test_status_without_id(self):
        self.reject("https://x.com/fixtureuser/status/")

    def test_non_numeric_status_id(self):
        self.reject("https://x.com/fixtureuser/status/abc")

    def test_overlong_id(self):
        self.reject("https://x.com/fixtureuser/status/" + "9" * 26)

    def test_unsupported_host(self):
        self.reject("https://example.com/fixtureuser/status/1000000000000000001")

    def test_garbage(self):
        self.reject("not a url at all")

    def test_error_carries_code(self):
        with self.assertRaises(m.InputError) as ctx:
            m.normalize_input("https://example.com/x/status/1")
        self.assertEqual(ctx.exception.code, m.E_INVALID_INPUT)


if __name__ == "__main__":
    unittest.main()
