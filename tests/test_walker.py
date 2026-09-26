"""Tests: Thread Walker (Tier 1) — slot selection, candidate extraction.

v3.2.0: discovery is dual-homed. Slot 1 is UnrollNow, slot 2 is
ThreadReaderApp; both are candidates-only sources (the truth layer is
`replying_to_status`). resolve_thread_ids returns (candidates, slot_name).
"""
import unittest
from unittest.mock import patch

from _loader import load_tool
import fixtures as fx

m = load_tool()


class TestCandidateExtraction(unittest.TestCase):
    def test_extract_ordered_deduped(self):
        # walker preserves first-seen HTML order (root appears last here via
        # canonical link; chain reconstruction reorders downstream anyway)
        html = fx.unrollnow_page(
            [fx.CHILD1_ID, fx.MEDIA_ID, fx.DECOY_ID, fx.CHILD1_ID],
            root_id=fx.ROOT_ID)
        with patch.object(m, "http_get", return_value=html.encode()):
            got, slot = m.resolve_thread_ids(fx.ROOT_ID)
        self.assertEqual(got, [fx.CHILD1_ID, fx.MEDIA_ID, fx.DECOY_ID, fx.ROOT_ID])
        self.assertEqual(slot, "unrollnow")

    def test_root_guaranteed_when_regex_misses_it(self):
        # short legacy IDs are invisible to the walker regex — root must be
        # prepended anyway (v2.0.0 silently dropped the root in this case)
        html = fx.unrollnow_page([fx.CHILD1_ID, fx.DECOY_ID])
        with patch.object(m, "http_get", return_value=html.encode()):
            got, slot = m.resolve_thread_ids("20")
        self.assertEqual(got[0], "20")
        self.assertIn(fx.CHILD1_ID, got)

    def test_bare_snowflake_ids_captured(self):
        html = fx.unrollnow_page([], noise_ids=[fx.MEDIA_ID])
        with patch.object(m, "http_get", return_value=html.encode()):
            got, _ = m.resolve_thread_ids(fx.ROOT_ID)
        self.assertIn(fx.MEDIA_ID, got)

    def test_candidates_capped(self):
        many = [f"10000000000000000{i:02d}" for i in range(80)]
        html = fx.unrollnow_page(many)
        with patch.object(m, "http_get", return_value=html.encode()):
            got, _ = m.resolve_thread_ids(fx.ROOT_ID)
        self.assertEqual(len(got), m.MAX_CANDIDATES)

    def test_cap_never_drops_root(self):
        # root appears late in a huge candidate list — cap must keep it
        many = [f"10000000000000000{i:02d}" for i in range(80)]
        html = fx.unrollnow_page(many + [fx.ROOT_ID])
        with patch.object(m, "http_get", return_value=html.encode()):
            got, _ = m.resolve_thread_ids(fx.ROOT_ID)
        self.assertEqual(len(got), m.MAX_CANDIDATES)
        self.assertIn(fx.ROOT_ID, got)

    def test_single_attempt_per_slot(self):
        # politeness contract: at most one request per walker slot per run
        html = fx.unrollnow_page([fx.CHILD1_ID])
        with patch.object(m, "http_get", return_value=html.encode()) as mock_get:
            m.resolve_thread_ids(fx.ROOT_ID)
        self.assertEqual(mock_get.call_count, 1)


class TestWalkerSlots(unittest.TestCase):
    def setUp(self):
        m.ERRORS.clear()

    def test_primary_serves_no_fallback_request(self):
        # when slot 1 answers, slot 2 must never be touched (politeness)
        html = fx.unrollnow_page([fx.CHILD1_ID], root_id=fx.ROOT_ID)
        with patch.object(m, "http_get", return_value=html.encode()) as mock_get:
            got, slot = m.resolve_thread_ids(fx.ROOT_ID)
        self.assertEqual(slot, "unrollnow")
        self.assertEqual(mock_get.call_count, 1)
        self.assertNotIn("threadreaderapp", mock_get.call_args_list[0].args[0])

    def test_primary_down_fallback_serves(self):
        # slot 1 network failure -> slot 2 takes the walk transparently
        tra = fx.threadreader_page([fx.CHILD1_ID, fx.DECOY_ID], root_id=fx.ROOT_ID)
        with patch.object(m, "http_get", side_effect=[OSError("timeout"), tra.encode()]) as mock_get:
            got, slot = m.resolve_thread_ids(fx.ROOT_ID)
        self.assertEqual(slot, "threadreaderapp")
        self.assertEqual(got, [fx.ROOT_ID, fx.CHILD1_ID, fx.DECOY_ID])
        self.assertEqual(mock_get.call_count, 2)
        # the primary failure is recorded, but the walk still succeeded
        self.assertTrue(any(e["code"] == m.E_WALKER_UNAVAILABLE for e in m.ERRORS))

    def test_primary_empty_fallback_serves(self):
        # slot 1 responds 200 but yields no candidates (layout change) ->
        # slot 2 gets its chance before degrading to root-only
        empty = fx.unrollnow_page([], root_id=fx.ROOT_ID)
        tra = fx.threadreader_page([fx.CHILD1_ID], root_id=fx.ROOT_ID)
        with patch.object(m, "http_get", side_effect=[empty.encode(), tra.encode()]):
            got, slot = m.resolve_thread_ids(fx.ROOT_ID)
        self.assertEqual(slot, "threadreaderapp")
        self.assertEqual(got, [fx.ROOT_ID, fx.CHILD1_ID])
        self.assertTrue(any(e["code"] == m.E_WALKER_EMPTY for e in m.ERRORS))

    def test_all_slots_fail_degrades_to_root(self):
        with patch.object(m, "http_get", side_effect=OSError("timeout")), \
                patch("time.sleep"):
            got, slot = m.resolve_thread_ids(fx.ROOT_ID)
        self.assertEqual(got, [fx.ROOT_ID])
        self.assertEqual(slot, "none")
        self.assertTrue(any(e["code"] == m.E_WALKER_UNAVAILABLE for e in m.ERRORS))

    def test_all_slots_empty_degrades_to_root(self):
        empty = fx.unrollnow_page([], root_id=fx.ROOT_ID)
        tra_empty = fx.threadreader_page([], root_id=fx.ROOT_ID)
        with patch.object(m, "http_get", side_effect=[empty.encode(), tra_empty.encode()]):
            got, slot = m.resolve_thread_ids(fx.ROOT_ID)
        self.assertEqual(got, [fx.ROOT_ID])
        self.assertEqual(slot, "none")

    def test_fallback_candidates_capped_root_kept(self):
        # the cap/root-guarantee contract holds no matter which slot served
        many = [f"10000000000000000{i:02d}" for i in range(80)]
        tra = fx.threadreader_page(many + [fx.ROOT_ID])
        with patch.object(m, "http_get", side_effect=[OSError("down"), tra.encode()]):
            got, slot = m.resolve_thread_ids(fx.ROOT_ID)
        self.assertEqual(slot, "threadreaderapp")
        self.assertEqual(len(got), m.MAX_CANDIDATES)
        self.assertIn(fx.ROOT_ID, got)

    def test_slot_urls_are_well_formed(self):
        # the slot templates must interpolate the root id into a clean https URL
        for name, template in m.WALKER_SLOTS:
            url = template.format(root="123")
            self.assertTrue(url.startswith("https://"))
            self.assertIn("123", url)


if __name__ == "__main__":
    unittest.main()
