"""Tests: Thread Walker (Tier 1) — candidate extraction from UnrollNow HTML."""
import unittest
from unittest.mock import patch

from _loader import load_tool
import fixtures as fx

m = load_tool()


class TestResolveThreadIds(unittest.TestCase):
    def test_extract_ordered_deduped(self):
        # walker preserves first-seen HTML order (root appears last here via
        # canonical link; chain reconstruction reorders downstream anyway)
        html = fx.unrollnow_page(
            [fx.CHILD1_ID, fx.MEDIA_ID, fx.DECOY_ID, fx.CHILD1_ID],
            root_id=fx.ROOT_ID)
        with patch.object(m, "http_get", return_value=html.encode()):
            got = m.resolve_thread_ids(fx.ROOT_ID)
        self.assertEqual(got, [fx.CHILD1_ID, fx.MEDIA_ID, fx.DECOY_ID, fx.ROOT_ID])

    def test_root_guaranteed_when_regex_misses_it(self):
        # short legacy IDs are invisible to the walker regex — root must be
        # prepended anyway (v2.0.0 silently dropped the root in this case)
        html = fx.unrollnow_page([fx.CHILD1_ID, fx.DECOY_ID])
        with patch.object(m, "http_get", return_value=html.encode()):
            got = m.resolve_thread_ids("20")
        self.assertEqual(got[0], "20")
        self.assertIn(fx.CHILD1_ID, got)

    def test_network_failure_degrades_to_root(self):
        with patch.object(m, "http_get", side_effect=OSError("timeout")), \
                patch("time.sleep"):
            got = m.resolve_thread_ids(fx.ROOT_ID)
        self.assertEqual(got, [fx.ROOT_ID])
        self.assertTrue(any(e["code"] == m.E_WALKER_UNAVAILABLE for e in m.ERRORS))

    def test_bare_snowflake_ids_captured(self):
        html = fx.unrollnow_page([], noise_ids=[fx.MEDIA_ID])
        with patch.object(m, "http_get", return_value=html.encode()):
            got = m.resolve_thread_ids(fx.ROOT_ID)
        self.assertIn(fx.MEDIA_ID, got)

    def test_candidates_capped(self):
        many = [f"10000000000000000{i:02d}" for i in range(80)]
        html = fx.unrollnow_page(many)
        with patch.object(m, "http_get", return_value=html.encode()):
            got = m.resolve_thread_ids(fx.ROOT_ID)
        self.assertEqual(len(got), m.MAX_CANDIDATES)

    def test_single_attempt_per_run(self):
        # politeness contract: the walker hits the source at most once
        html = fx.unrollnow_page([fx.CHILD1_ID])
        with patch.object(m, "http_get", return_value=html.encode()) as mock_get:
            m.resolve_thread_ids(fx.ROOT_ID)
        self.assertEqual(mock_get.call_count, 1)


if __name__ == "__main__":
    unittest.main()

    def test_cap_never_drops_root(self):
        # root appears late in a huge candidate list — cap must keep it
        many = [f"10000000000000000{i:02d}" for i in range(80)]
        html = fx.unrollnow_page(many + [fx.ROOT_ID])
        with patch.object(m, "http_get", return_value=html.encode()):
            got = m.resolve_thread_ids(fx.ROOT_ID)
        self.assertEqual(len(got), m.MAX_CANDIDATES)
        self.assertIn(fx.ROOT_ID, got)

    def test_empty_page_records_walker_empty(self):
        html = fx.unrollnow_page([])  # 200 OK but no candidate ids (layout change)
        m.ERRORS.clear()
        with patch.object(m, "http_get", return_value=html.encode()):
            got = m.resolve_thread_ids(fx.ROOT_ID)
        self.assertEqual(got, [fx.ROOT_ID])
        self.assertTrue(any(e["code"] == m.E_WALKER_EMPTY for e in m.ERRORS))
