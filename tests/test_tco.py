"""Tests: t.co shortlink expansion (v3.2.0) — offline, urlopen is mocked."""
import unittest
from unittest.mock import patch

from _loader import load_tool

m = load_tool()


class FakeResponse:
    """Minimal urlopen() stand-in: geturl() reports the redirect destination."""

    def __init__(self, dest, body=b""):
        self._dest = dest
        self._body = body

    def geturl(self):
        return self._dest

    def read(self, n=-1):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestIsTco(unittest.TestCase):
    def test_tco_forms_detected(self):
        for inp in ("https://t.co/abc123", "t.co/abc123", "https://www.t.co/abc123",
                    "  t.co/abc123  "):
            self.assertTrue(m.is_tco(inp), inp)

    def test_non_tco_rejected(self):
        for inp in ("https://x.com/u/status/123", "example.com", "", "   ",
                    "https://evil.com/t.co/abc"):
            self.assertFalse(m.is_tco(inp), inp)


class TestExpandTco(unittest.TestCase):
    def test_resolves_to_status_url(self):
        with patch.object(m.urllib.request, "urlopen",
                          return_value=FakeResponse("https://x.com/user/status/123")):
            dest = m.expand_tco("https://t.co/abc123")
        self.assertEqual(dest, "https://x.com/user/status/123")

    def test_resolves_legacy_twitter_host(self):
        with patch.object(m.urllib.request, "urlopen",
                          return_value=FakeResponse("https://twitter.com/u/status/999")):
            dest = m.expand_tco("t.co/abc123")
        self.assertEqual(dest, "https://twitter.com/u/status/999")

    def test_non_status_destination_rejected(self):
        with patch.object(m.urllib.request, "urlopen",
                          return_value=FakeResponse("https://example.com/page")):
            with self.assertRaises(m.InputError) as ctx:
                m.expand_tco("https://t.co/abc123")
        self.assertIn("does not point", str(ctx.exception))

    def test_interstitial_meta_refresh_parsed(self):
        # t.co serves some clients a 200 page embedding the target in a
        # <noscript> meta-refresh instead of an HTTP redirect — parse it
        body = (b'<head><noscript><META http-equiv="refresh" '
                b'content="0;URL=https://x.com/user/status/42"></noscript></head>')
        with patch.object(m.urllib.request, "urlopen",
                          return_value=FakeResponse("https://t.co/abc123", body)):
            dest = m.expand_tco("https://t.co/abc123")
        self.assertEqual(dest, "https://x.com/user/status/42")

    def test_interstitial_location_replace_parsed(self):
        # second interstitial shape: location.replace("http:\/\/host\/path")
        body = (b'<script>window.opener = null; '
                b'location.replace("https:\\/\\/twitter.com\\/u\\/status\\/99")</script>')
        with patch.object(m.urllib.request, "urlopen",
                          return_value=FakeResponse("https://t.co/abc123", body)):
            dest = m.expand_tco("https://t.co/abc123")
        self.assertEqual(dest, "https://twitter.com/u/status/99")

    def test_interstitial_to_external_host_rejected_with_real_host(self):
        # live-observed shape: interstitial points at an external site —
        # the rejection must name the real destination host, not t.co
        body = (b'<noscript><META http-equiv="refresh" '
                b'content="0;URL=http://Terafab.AI"></noscript>')
        with patch.object(m.urllib.request, "urlopen",
                          return_value=FakeResponse("https://t.co/abc123", body)):
            with self.assertRaises(m.InputError) as ctx:
                m.expand_tco("https://t.co/abc123")
        self.assertIn("terafab.ai", str(ctx.exception))

    def test_unparseable_interstitial_rejected(self):
        # dead link: still on t.co, no embedded target anywhere
        with patch.object(m.urllib.request, "urlopen",
                          return_value=FakeResponse("https://t.co/abc123", b"<p>gone</p>")):
            with self.assertRaises(m.InputError) as ctx:
                m.expand_tco("https://t.co/abc123")
        self.assertIn("did not redirect", str(ctx.exception))

    def test_network_failure_is_input_error(self):
        with patch.object(m.urllib.request, "urlopen", side_effect=OSError("timeout")):
            with self.assertRaises(m.InputError) as ctx:
                m.expand_tco("https://t.co/abc123")
        self.assertIn("resolution failed", str(ctx.exception))

    def test_empty_input_rejected(self):
        with self.assertRaises(m.InputError):
            m.expand_tco("")

    def test_non_tco_host_rejected_before_network(self):
        # guard: expand_tco is for t.co only — never a general fetcher
        with patch.object(m.urllib.request, "urlopen") as mock_open:
            with self.assertRaises(m.InputError):
                m.expand_tco("https://example.com/x")
        mock_open.assert_not_called()


class TestMainWiring(unittest.TestCase):
    def test_cli_accepts_tco_input(self):
        # the CLI resolves a t.co input and harvests the destination —
        # verified end-to-end with both network layers patched
        info_target = "https://x.com/fixtureuser/status/1000000000000000001"
        tweet = {
            "id": "1000000000000000001", "url": info_target,
            "text": "fixture", "author": {"screen_name": "fixtureuser"},
            "created_at": None, "created_timestamp": None,
        }
        with patch.object(m, "expand_tco", return_value=info_target) as mock_exp, \
                patch.object(m, "fetch_tweet", return_value=dict(tweet)), \
                patch.object(m, "resolve_thread_ids",
                             return_value=(["1000000000000000001"], "unrollnow")), \
                patch.object(m, "download"):
            argv = ["xthread-agent", "https://t.co/abc123", "--out",
                    "/tmp/xt_tco_test", "--no-download", "--json", "--quiet"]
            with patch.object(m.sys, "argv", argv):
                rc = m.main()
        self.assertEqual(rc, 0)
        mock_exp.assert_called_once_with("https://t.co/abc123")

    def test_cli_non_tco_invalid_input_stays_invalid(self):
        with patch.object(m, "expand_tco") as mock_exp:
            argv = ["xthread-agent", "https://example.com/status/1", "--json",
                    "--quiet", "--out", "/tmp/xt_tco_test2"]
            with patch.object(m.sys, "argv", argv):
                rc = m.main()
        self.assertEqual(rc, 1)
        mock_exp.assert_not_called()  # non-t.co rejection must not touch network


if __name__ == "__main__":
    unittest.main()
