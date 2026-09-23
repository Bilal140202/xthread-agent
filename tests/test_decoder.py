"""Tests: Metadata Decoder (Tier 2) — FixTweet slot + vxtwitter fallback."""
import json
import unittest
import urllib.error
from unittest.mock import patch

from _loader import load_tool
import fixtures as fx

m = load_tool()


def fxt_response(tweet):
    return json.dumps({"code": 200, "message": "OK", "tweet": tweet}).encode()


class TestFetchTweet(unittest.TestCase):
    def test_ok_payload_tagged_fxtwitter(self):
        with patch.object(m, "http_get", return_value=fxt_response({"id": fx.ROOT_ID, "text": "x"})):
            tw = m.fetch_tweet(fx.ROOT_ID)
        self.assertEqual(tw["id"], fx.ROOT_ID)
        self.assertEqual(tw["_extraction_source"], "fxtwitter")

    def test_404_is_filter_signal_no_retry(self):
        body = json.dumps({"code": 404, "message": "NOT_FOUND", "tweet": None}).encode()
        with patch.object(m, "http_get", return_value=body) as mock_get:
            got = m.fetch_tweet(fx.MEDIA_ID)
        self.assertIsNone(got)
        self.assertEqual(mock_get.call_count, 1)  # zero retries on 404
        self.assertEqual(m.ERRORS, [])            # silent by contract

    def test_network_failure_uses_fallback(self):
        with patch.object(m, "http_get", side_effect=OSError("conn reset")), \
                patch.object(m, "_fetch_vxtweet",
                             return_value=m._normalize_vxtweet(fx.vxtweet())), \
                patch("time.sleep"):
            tw = m.fetch_tweet(fx.ROOT_ID)
        self.assertIsNotNone(tw)
        self.assertEqual(tw["_extraction_source"], "vxtwitter")

    def test_all_slots_exhausted_records_error(self):
        with patch.object(m, "http_get", side_effect=OSError("down")), \
                patch.object(m, "_fetch_vxtweet", return_value=None), \
                patch("time.sleep"):
            got = m.fetch_tweet(fx.ROOT_ID)
        self.assertIsNone(got)
        self.assertTrue(any(e["code"] == m.E_DECODE_FAILED for e in m.ERRORS))

    def test_real_http_404_is_filter_signal_no_retry(self):
        # live-verified behavior: FixTweet returns actual HTTP 404 statuses
        # (urllib raises HTTPError) — must filter instantly, never retry
        err = urllib.error.HTTPError("https://api.fxtwitter.com/status/x", 404,
                                     "Not Found", None, None)
        with patch.object(m, "http_get", side_effect=err) as mock_get:
            got = m.fetch_tweet(fx.MEDIA_ID)
        self.assertIsNone(got)
        self.assertEqual(mock_get.call_count, 1)

    def test_http_451_is_filter_signal(self):
        err = urllib.error.HTTPError("https://api.fxtwitter.com/status/x", 451,
                                     "Unavailable For Legal Reasons", None, None)
        with patch.object(m, "http_get", side_effect=err) as mock_get:
            got = m.fetch_tweet(fx.MEDIA_ID)
        self.assertIsNone(got)
        self.assertEqual(mock_get.call_count, 1)

    def test_http_429_is_retried(self):
        err = urllib.error.HTTPError("https://api.fxtwitter.com/status/x", 429,
                                     "Too Many Requests", None, None)
        body = json.dumps({"code": 200, "tweet": {"id": fx.ROOT_ID}}).encode()
        with patch.object(m, "http_get", side_effect=[err, body]), \
                patch("time.sleep"):
            tw = m.fetch_tweet(fx.ROOT_ID)
        self.assertIsNotNone(tw)

    def test_retries_on_non404_error_code(self):
        # first attempt: 500; second: OK — must retry (404 never reaches here)
        responses = [json.dumps({"code": 500}).encode(),
                     fxt_response({"id": fx.ROOT_ID})]
        with patch.object(m, "http_get", side_effect=responses), \
                patch("time.sleep"):
            tw = m.fetch_tweet(fx.ROOT_ID, tries=3)
        self.assertIsNotNone(tw)


class TestNormalizeVxtweet(unittest.TestCase):
    def test_shape(self):
        norm = m._normalize_vxtweet(fx.vxtweet())
        self.assertEqual(norm["id"], fx.ROOT_ID)
        self.assertEqual(norm["author"]["screen_name"], "fixtureuser")
        self.assertEqual(len(norm["media"]["photos"]), 1)
        self.assertEqual(len(norm["media"]["videos"]), 1)
        self.assertIsNone(norm["views"])  # absent fields are explicit nulls

    def test_invalid_payload_rejected(self):
        self.assertIsNone(m._normalize_vxtweet(None))
        self.assertIsNone(m._normalize_vxtweet({}))
        self.assertIsNone(m._normalize_vxtweet({"tweetID": None}))

    def test_qrt_normalized_one_level(self):
        vx = fx.vxtweet()
        vx["qrt"] = {"tweetID": "1000000000000000077", "text": "inner",
                     "media_extended": [], "qrt": {"tweetID": "1"}}
        norm = m._normalize_vxtweet(vx)
        self.assertEqual(norm["quote"]["id"], "1000000000000000077")
        self.assertIsNone(norm["quote"]["quote"])  # depth bounded


if __name__ == "__main__":
    unittest.main()

    def test_bogus_tweet_id_rejected(self):
        # a compromised/broken decoder must not inject non-digit ids that end
        # up in filenames (path traversal guard)
        body = fxt_response({"id": "../../evil", "text": "x"})
        with patch.object(m, "http_get", return_value=body):
            got = m.fetch_tweet(fx.ROOT_ID)
        self.assertIsNone(got)
