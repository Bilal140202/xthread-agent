"""Tests: payload mapping (FixTweet/vxtwitter → stable schema)."""
import unittest

from _loader import load_tool
import fixtures as fx

m = load_tool()


class TestMapAuthor(unittest.TestCase):
    def test_full_mapping(self):
        a = m.map_author(fx.AUTHOR)
        self.assertEqual(a["screen_name"], "fixtureuser")
        self.assertEqual(a["followers"], 1000)
        self.assertTrue(a["verified"])
        self.assertFalse(a["protected"])
        self.assertEqual(a["website"]["display_url"], "example.com/fixture")

    def test_null_author(self):
        a = m.map_author(None)
        self.assertIsNone(a["screen_name"])
        self.assertIsNone(a["followers"])
        self.assertFalse(a["verified"])


class TestMapVideo(unittest.TestCase):
    def test_direct_mp4(self):
        v = m.map_video(fx.video())
        self.assertIn(".mp4", v["url"])
        self.assertTrue(v["downloadable"])
        self.assertIsNone(v["playlist_url"])
        self.assertEqual(v["duration"], 41.6)
        self.assertIsNone(v["file"])

    def test_m3u8_falls_back_to_best_mp4_variant(self):
        v = m.map_video(fx.hls_video_with_mp4_variants())
        self.assertIn("fixture_c.mp4", v["url"])   # highest bitrate
        self.assertIn(".m3u8", v["playlist_url"])
        self.assertTrue(v["downloadable"])

    def test_m3u8_without_variants_not_downloadable(self):
        v = m.map_video(fx.video(url="https://video.twimg.com/x/pl/fixture.m3u8?tag=14"))
        self.assertFalse(v["downloadable"])
        self.assertIsNone(v["file"])

    def test_variants_capped(self):
        v = fx.video(formats=[{"url": f"https://video.twimg.com/v{i}.mp4",
                               "container": "mp4", "bitrate": i} for i in range(20)])
        self.assertEqual(len(m.map_video(v)["variants"]), 10)


class TestMapPhoto(unittest.TestCase):
    def test_full(self):
        p = m.map_photo(fx.photo(alt="a fixture image"))
        self.assertEqual(p["alt_text"], "a fixture image")
        self.assertEqual(p["width"], 1200)
        self.assertIsNone(p["file"])

    def test_null(self):
        p = m.map_photo(None)
        self.assertIsNone(p["url"])


class TestMapTweet(unittest.TestCase):
    def test_metrics_and_nullability(self):
        post = m.map_tweet(fx.fxtweet())
        self.assertEqual(post["metrics"]["likes"], 5)
        self.assertEqual(post["thread_position"], None)
        self.assertIsNone(post["replying_to_status"])
        self.assertEqual(post["extraction_source"], "fxtwitter")

    def test_iso_timestamp(self):
        post = m.map_tweet(fx.fxtweet(created_timestamp=1700000000))
        self.assertEqual(post["created_at_iso"], "2023-11-14T22:13:20Z")
        self.assertEqual(post["created_at"], "Tue Nov 14 22:13:20 +0000 2023")

    def test_bad_timestamp_is_null_not_crash(self):
        post = m.map_tweet(fx.fxtweet(created_timestamp="not-a-number"))
        self.assertIsNone(post["created_at_iso"])

    def test_quoted_post_depth_one(self):
        inner_quote = fx.fxtweet(tid="1000000000000000078", text="deep fixture")
        outer = fx.fxtweet(quote=fx.fxtweet(quote=inner_quote, text="middle fixture"))
        post = m.map_tweet(outer)
        self.assertEqual(post["quoted_post"]["text"], "middle fixture")
        self.assertEqual(post["quoted_post"]["thread_position"], None)
        self.assertIsNone(post["quoted_post"]["quoted_post"])  # depth bounded

    def test_media_url_deduped(self):
        dup = "https://pbs.twimg.com/media/fixturedup?format=jpg&name=large"
        tw = fx.fxtweet(photos=[fx.photo(url=dup), fx.photo(url=dup)])
        post = m.map_tweet(tw)
        self.assertEqual(len(post["media"]["photos"]), 1)

    def test_url_fallback_without_payload_url(self):
        tw = fx.fxtweet()
        tw.pop("url")
        post = m.map_tweet(tw)
        self.assertEqual(post["url"],
                         f"https://x.com/fixtureuser/status/{fx.ROOT_ID}")


if __name__ == "__main__":
    unittest.main()
