"""Tests: Media Fetcher (Tier 3) — streaming, atomicity, resumability."""
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _loader import load_tool

m = load_tool()


class _FakeResponse:
    def __init__(self, chunks, fail_after=None):
        self._stream = io.BytesIO(chunks)
        self._fail_after = fail_after
        self.headers = {"Content-Length": str(len(chunks))}

    def read(self, n):
        return self._stream.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestDownload(unittest.TestCase):
    """fake_urlopen returns a context-manager response ignoring call args
    (the tool calls urlopen(req, timeout=...))."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _fake_urlopen(self, chunks=b"x" * 100):
        return lambda *a, **k: _FakeResponse(chunks)

    def test_success_atomic_no_part_left(self):
        dest = self.out / "f.mp4"
        with patch.object(m.urllib.request, "urlopen",
                          self._fake_urlopen(b"0123456789")):
            ok = m.download("https://video.twimg.com/fixture.mp4", dest)
        self.assertTrue(ok)
        self.assertEqual(dest.read_bytes(), b"0123456789")
        self.assertFalse((self.out / "f.mp4.part").exists())

    def test_skip_if_exists_never_hits_network(self):
        dest = self.out / "f.mp4"
        dest.write_bytes(b"already here")
        with patch.object(m.urllib.request, "urlopen") as mock_open:
            ok = m.download("https://video.twimg.com/fixture.mp4", dest)
        self.assertTrue(ok)
        mock_open.assert_not_called()

    def test_failure_leaves_no_file_and_no_part(self):
        dest = self.out / "f.mp4"

        def boom(*a, **k):
            raise OSError("network down")

        with patch.object(m.urllib.request, "urlopen", boom), \
                patch("time.sleep"):
            ok = m.download("https://video.twimg.com/fixture.mp4", dest, tries=2)
        self.assertFalse(ok)
        self.assertFalse(dest.exists())
        self.assertFalse((self.out / "f.mp4.part").exists())
        self.assertTrue(any(e["code"] == m.E_DOWNLOAD_FAILED for e in m.ERRORS))

    def test_empty_body_rejected(self):
        dest = self.out / "f.mp4"
        with patch.object(m.urllib.request, "urlopen", self._fake_urlopen(b"")), \
                patch("time.sleep"):
            ok = m.download("https://video.twimg.com/fixture.mp4", dest, tries=1)
        self.assertFalse(ok)
        self.assertFalse(dest.exists())

    def test_corrupt_leftover_part_not_treated_as_complete(self):
        # a crashed earlier run may leave a .part file — it must be re-downloaded
        dest = self.out / "f.mp4"
        (self.out / "f.mp4.part").write_bytes(b"trunca")
        with patch.object(m.urllib.request, "urlopen",
                          self._fake_urlopen(b"0123456789")):
            ok = m.download("https://video.twimg.com/fixture.mp4", dest)
        self.assertTrue(ok)
        self.assertEqual(dest.read_bytes(), b"0123456789")

    def test_zero_byte_dest_not_treated_as_complete(self):
        dest = self.out / "f.mp4"
        dest.write_bytes(b"")
        with patch.object(m.urllib.request, "urlopen", self._fake_urlopen(b"real")):
            ok = m.download("https://video.twimg.com/fixture.mp4", dest)
        self.assertTrue(ok)
        self.assertEqual(dest.read_bytes(), b"real")


class TestExtFromUrl(unittest.TestCase):
    def test_twimg_size_suffix(self):
        self.assertEqual(m._ext_from_url("https://pbs.twimg.com/media/x.jpg:large", ".jpg"), ".jpg")

    def test_format_query(self):
        self.assertEqual(m._ext_from_url("https://pbs.twimg.com/media/x?format=png&name=large", ".jpg"), ".png")

    def test_default(self):
        self.assertEqual(m._ext_from_url("https://pbs.twimg.com/media/x", ".jpg"), ".jpg")

    def test_mp4(self):
        self.assertEqual(m._ext_from_url("https://video.twimg.com/x/fixture.mp4?tag=14", ".mp4"), ".mp4")


if __name__ == "__main__":
    unittest.main()


class TestMediaUrlAllowlist(unittest.TestCase):
    """QA regression: media URLs come from remote decoder payloads — the
    fetcher must refuse local-file and non-CDN targets (SSRF/LFI guard)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        m.ERRORS.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def test_refuses_file_scheme(self):
        ok = m.download("file:///etc/hostname", self.out / "x.jpg", tries=1)
        self.assertFalse(ok)
        self.assertFalse((self.out / "x.jpg").exists())

    def test_refuses_non_twimg_host(self):
        ok = m.download("https://evil.example.com/fixture.mp4", self.out / "x.mp4", tries=1)
        self.assertFalse(ok)

    def test_allows_twimg_hosts(self):
        for host in ("video.twimg.com", "pbs.twimg.com", "ton.twimg.com"):
            url = f"https://{host}/fixture/x.mp4"
            with patch.object(m.urllib.request, "urlopen",
                              lambda *a, **k: _FakeResponse(b"data")), \
                    patch("time.sleep"):
                self.assertTrue(m.download(url, self.out / f"{host}.mp4"), url)

    def test_truncated_transfer_rejected(self):
        # server declares 1000 bytes but sends 100 — must fail, not corrupt
        dest = self.out / "x.mp4"
        resp = _FakeResponse(b"x" * 100)
        resp.headers = {"Content-Length": "1000"}
        with patch.object(m.urllib.request, "urlopen", lambda *a, **k: resp), \
                patch("time.sleep"):
            ok = m.download("https://video.twimg.com/fixture/x.mp4", dest, tries=1)
        self.assertFalse(ok)
        self.assertFalse(dest.exists())
        self.assertFalse((self.out / "x.mp4.part").exists())

    def test_matching_content_length_accepted(self):
        dest = self.out / "x.mp4"
        with patch.object(m.urllib.request, "urlopen",
                          lambda *a, **k: _FakeResponse(b"0123456789")):
            ok = m.download("https://video.twimg.com/fixture/x.mp4", dest)
        self.assertTrue(ok)
        self.assertEqual(dest.stat().st_size, 10)
