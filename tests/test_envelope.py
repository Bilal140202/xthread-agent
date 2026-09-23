"""Tests: orchestrator envelope assembly (harvest) — integration level."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _loader import load_tool
import fixtures as fx

m = load_tool()


class HarvestHarness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        m.ERRORS.clear()

    def tearDown(self):
        self.tmp.cleanup()

    # -- patch helpers -----------------------------------------------------
    def patch_network(self, walker_ids, tweets_by_id, downloads=None):
        """Patch walker + decoder + downloader with synthetic data."""
        html = fx.unrollnow_page(walker_ids, root_id=fx.ROOT_ID)
        self._dl_calls = []

        def fake_download(url, dest, tries=3):
            self._dl_calls.append(url)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"fixturebytes")
            return True

        def fake_fetch(tid, tries=3):
            tw = tweets_by_id.get(tid)
            return dict(tw) if tw else None

        p1 = patch.object(m, "resolve_thread_ids", return_value=list(walker_ids))
        p2 = patch.object(m, "fetch_tweet", side_effect=fake_fetch)
        p3 = patch.object(m, "download", side_effect=fake_download)
        return p1, p2, p3


class TestHarvestEnvelope(HarvestHarness):
    def test_happy_path_chain(self):
        tweets = {
            fx.ROOT_ID: fx.fxtweet(fx.ROOT_ID, text="fixture unicode ✓ 中文 🧵"),
            fx.CHILD1_ID: fx.fxtweet(fx.CHILD1_ID, text="fixture reply 1",
                                     replying_to="fixtureuser",
                                     replying_to_status=fx.ROOT_ID,
                                     photos=[fx.photo()]),
            fx.CHILD2_ID: fx.fxtweet(fx.CHILD2_ID, text="fixture reply 2",
                                     replying_to="fixtureuser",
                                     replying_to_status=fx.CHILD1_ID,
                                     videos=[fx.video()]),
            fx.DECOY_ID: fx.fxtweet(fx.DECOY_ID, text="unrelated same-author post"),
        }
        p1, p2, p3 = self.patch_network(
            [fx.ROOT_ID, fx.CHILD1_ID, fx.DECOY_ID, fx.MEDIA_ID, fx.CHILD2_ID],
            tweets)
        with p1, p2, p3:
            env = m.harvest(fx.ROOT_ID, self.out, do_download=True,
                            request_info={"input": "x", "canonical_url": "y"},
                            decode_sleep=0)

        self.assertEqual(env["schema_version"], "3.0")
        self.assertEqual(env["status"], "ok")
        self.assertEqual([p["id"] for p in env["posts"]],
                         [fx.ROOT_ID, fx.CHILD1_ID, fx.CHILD2_ID])
        self.assertEqual(env["thread"]["related_filtered"], 1)
        self.assertEqual(env["thread"]["walker_candidates"], 5)
        self.assertEqual(env["thread"]["decoded_tweets"], 4)
        self.assertEqual(env["thread"]["media_ids_filtered"], 1)
        self.assertEqual(env["errors"], [])
        self.assertEqual(env["metadata"]["counts"]["photos"], 1)
        self.assertEqual(env["metadata"]["counts"]["videos"], 1)
        self.assertEqual(env["metadata"]["counts"]["downloaded_media"], 2)
        self.assertEqual(env["posts"][0]["thread_position"], 0)
        self.assertEqual(env["posts"][2]["thread_position"], 2)
        # unicode survived (UTF-8, not escaped)
        self.assertIn("中文", env["posts"][0]["text"])

    def test_manifest_written_utf8(self):
        tweets = {fx.ROOT_ID: fx.fxtweet(text="fixture unicode ✓ 中文")}
        p1, p2, p3 = self.patch_network([fx.ROOT_ID], tweets)
        with p1, p2, p3:
            m.harvest(fx.ROOT_ID, self.out, do_download=False, decode_sleep=0)
        raw = (self.out / "thread_manifest.json").read_bytes()
        self.assertIn("中文".encode("utf-8"), raw)
        env = json.loads(raw.decode("utf-8"))
        self.assertEqual(env["thread"]["tweet_count"], 1)

    def test_root_unavailable_empty_status(self):
        p1, p2, p3 = self.patch_network([fx.ROOT_ID], {})
        with p1, p2, p3:
            env = m.harvest(fx.ROOT_ID, self.out, do_download=False, decode_sleep=0)
        self.assertEqual(env["status"], "empty")
        self.assertEqual(env["posts"], [])
        self.assertTrue(any(e["code"] == m.E_ROOT_UNAVAILABLE for e in env["errors"]))
        self.assertFalse(env["thread"]["chain_reconstructed"])

    def test_walker_failure_degrades_to_root(self):
        def fake_walk(root_id):
            m.record_error("walker", m.E_WALKER_UNAVAILABLE, "walk down")
            return [root_id]

        tweets = {fx.ROOT_ID: fx.fxtweet()}
        with patch.object(m, "resolve_thread_ids", side_effect=fake_walk), \
                patch.object(m, "fetch_tweet", side_effect=lambda t, tries=3: dict(tweets[t])), \
                patch.object(m, "download"):
            env = m.harvest(fx.ROOT_ID, self.out, do_download=False, decode_sleep=0)
        self.assertEqual(env["status"], "partial")
        self.assertTrue(env["thread"]["degraded_to_root_only"])
        self.assertEqual(env["thread"]["tweet_count"], 1)

    def test_decode_failure_marks_partial(self):
        tweets = {fx.ROOT_ID: fx.fxtweet()}
        real_fetch = m.fetch_tweet

        def fake_fetch(tid, tries=3):
            if tid == fx.ROOT_ID:
                return dict(tweets[fx.ROOT_ID])
            m.record_error("decoder", m.E_DECODE_FAILED, "boom", subject=tid)
            return None

        with patch.object(m, "resolve_thread_ids", return_value=[fx.ROOT_ID, fx.CHILD1_ID]), \
                patch.object(m, "fetch_tweet", side_effect=fake_fetch), \
                patch.object(m, "download"):
            env = m.harvest(fx.ROOT_ID, self.out, do_download=False, decode_sleep=0)
        self.assertEqual(env["status"], "partial")
        self.assertTrue(any(e["code"] == m.E_DECODE_FAILED for e in env["errors"]))

    def test_download_failure_recorded_and_partial(self):
        tweets = {fx.ROOT_ID: fx.fxtweet(photos=[fx.photo()])}

        def fake_download_fail(url, dest, tries=3):
            m.record_error("fetcher", m.E_DOWNLOAD_FAILED,
                           "download failed after 3 attempts", subject=url)
            return False

        with patch.object(m, "resolve_thread_ids", return_value=[fx.ROOT_ID]), \
                patch.object(m, "fetch_tweet", side_effect=lambda t, tries=3: dict(tweets[t])), \
                patch.object(m, "download", side_effect=fake_download_fail):
            env = m.harvest(fx.ROOT_ID, self.out, do_download=True, decode_sleep=0)
        self.assertEqual(env["status"], "partial")
        self.assertEqual(env["metadata"]["counts"]["failed_downloads"], 1)
        self.assertEqual(env["metadata"]["counts"]["downloaded_media"], 0)
        self.assertTrue(any(e["code"] == m.E_DOWNLOAD_FAILED for e in env["errors"]))

    def test_no_download_leaves_files_null(self):
        tweets = {fx.ROOT_ID: fx.fxtweet(photos=[fx.photo()], videos=[fx.video()])}
        with patch.object(m, "resolve_thread_ids", return_value=[fx.ROOT_ID]), \
                patch.object(m, "fetch_tweet", side_effect=lambda t, tries=3: dict(tweets[t])), \
                patch.object(m, "download"):
            env = m.harvest(fx.ROOT_ID, self.out, do_download=False, decode_sleep=0)
        media = env["posts"][0]["media"]
        self.assertIsNone(media["photos"][0]["file"])
        self.assertFalse(media["photos"][0]["downloaded"])
        self.assertIsNone(media["videos"][0]["file"])
        self.assertIsNotNone(media["videos"][0]["url"])

    def test_hls_only_video_explained_not_silent(self):
        tweets = {fx.ROOT_ID: fx.fxtweet(
            videos=[fx.video(url="https://video.twimg.com/x/pl/fixture.m3u8")])}
        with patch.object(m, "resolve_thread_ids", return_value=[fx.ROOT_ID]), \
                patch.object(m, "fetch_tweet", side_effect=lambda t, tries=3: dict(tweets[t])), \
                patch.object(m, "download"):
            env = m.harvest(fx.ROOT_ID, self.out, do_download=True, decode_sleep=0)
        v = env["posts"][0]["media"]["videos"][0]
        self.assertFalse(v["downloadable"])
        self.assertEqual(v["reason"], "hls_only")
        self.assertIsNone(v["file"])

    def test_quoted_post_in_envelope(self):
        tweets = {fx.ROOT_ID: fx.fxtweet(quote=fx.quote_tweet())}
        with patch.object(m, "resolve_thread_ids", return_value=[fx.ROOT_ID]), \
                patch.object(m, "fetch_tweet", side_effect=lambda t, tries=3: dict(tweets[t])), \
                patch.object(m, "download"):
            env = m.harvest(fx.ROOT_ID, self.out, do_download=False, decode_sleep=0)
        q = env["posts"][0]["quoted_post"]
        self.assertEqual(q["id"], "1000000000000000077")
        self.assertEqual(len(q["media"]["photos"]), 1)
        self.assertEqual(len(q["media"]["videos"]), 1)


if __name__ == "__main__":
    unittest.main()
