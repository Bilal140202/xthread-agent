"""Tests: thread reconstruction from replying_to_status chains."""
import unittest
from unittest.mock import patch

from _loader import load_tool
import fixtures as fx

m = load_tool()


def decoded_chain():
    root = fx.fxtweet(fx.ROOT_ID)
    child1 = fx.fxtweet(fx.CHILD1_ID, text="fixture reply 1",
                        replying_to="fixtureuser",
                        replying_to_status=fx.ROOT_ID)
    child2 = fx.fxtweet(fx.CHILD2_ID, text="fixture reply 2",
                        replying_to="fixtureuser",
                        replying_to_status=fx.CHILD1_ID)
    return {fx.ROOT_ID: root, fx.CHILD1_ID: child1, fx.CHILD2_ID: child2}


class TestReconstructThread(unittest.TestCase):
    def test_chain_built_from_polluted_candidates(self):
        # decoded contains the chain PLUS same-author recommendations and
        # other-author replies — only chain members may survive
        decoded = decoded_chain()
        decoded[fx.DECOY_ID] = fx.fxtweet(fx.DECOY_ID, text="unrelated fixture post")
        decoded[fx.STRANGER_ID] = fx.fxtweet(
            fx.STRANGER_ID, text="stranger fixture reply",
            replying_to="fixtureuser", replying_to_status=fx.ROOT_ID,
            screen_name="strangeruser")

        with patch("time.sleep"):
            chain, stats = m.reconstruct_thread(fx.ROOT_ID, decoded,
                                                lambda tid: None)
        self.assertEqual([tw["id"] for tw in chain],
                         [fx.ROOT_ID, fx.CHILD1_ID, fx.CHILD2_ID])
        self.assertEqual(stats["chain_length"], 3)
        self.assertEqual(stats["ancestors_fetched"], 0)

    def test_ancestor_walk_up(self):
        # requested root is a MID-chain reply; the true start is missing from
        # candidates and must be fetched through the decoder
        decoded = {fx.ROOT_ID: fx.fxtweet(
            fx.ROOT_ID, replying_to="fixtureuser",
            replying_to_status=fx.PARENT_ID)}

        fetched = []
        def fake_fetch(tid):
            fetched.append(tid)
            if tid == fx.PARENT_ID:
                return fx.fxtweet(fx.PARENT_ID, text="thread start")
            return None

        with patch("time.sleep"):
            chain, stats = m.reconstruct_thread(fx.ROOT_ID, decoded, fake_fetch)
        self.assertEqual(fetched, [fx.PARENT_ID])
        self.assertEqual([tw["id"] for tw in chain], [fx.PARENT_ID, fx.ROOT_ID])
        self.assertEqual(stats["ancestors_fetched"], 1)

    def test_ancestor_walk_stops_on_author_change(self):
        decoded = {fx.ROOT_ID: fx.fxtweet(
            fx.ROOT_ID, replying_to="strangeruser",
            replying_to_status=fx.STRANGER_ID)}
        parent = fx.fxtweet(fx.STRANGER_ID, text="stranger post",
                            screen_name="strangeruser")

        with patch("time.sleep"):
            chain, stats = m.reconstruct_thread(
                fx.ROOT_ID, decoded, lambda tid: parent if tid == fx.STRANGER_ID else None)
        # parent is a different author -> NOT part of the self-reply chain
        self.assertEqual([tw["id"] for tw in chain], [fx.ROOT_ID])
        self.assertEqual(stats["ancestors_fetched"], 0)

    def test_ancestor_walk_stops_on_unavailable_parent(self):
        decoded = {fx.ROOT_ID: fx.fxtweet(
            fx.ROOT_ID, replying_to="fixtureuser",
            replying_to_status=fx.PARENT_ID)}
        with patch("time.sleep"):
            chain, stats = m.reconstruct_thread(fx.ROOT_ID, decoded, lambda tid: None)
        self.assertEqual([tw["id"] for tw in chain], [fx.ROOT_ID])

    def test_ancestor_cap(self):
        # a pathological long ancestor chain is bounded by MAX_ANCESTORS
        decoded = {fx.ROOT_ID: fx.fxtweet(
            fx.ROOT_ID, replying_to="fixtureuser",
            replying_to_status="1000000000000000099")}

        def fake_fetch(tid):
            n = int(tid)
            return fx.fxtweet(str(n), replying_to="fixtureuser",
                              replying_to_status=str(n - 1))

        with patch("time.sleep"):
            chain, stats = m.reconstruct_thread(fx.ROOT_ID, decoded, fake_fetch)
        self.assertEqual(stats["ancestors_fetched"], m.MAX_ANCESTORS)

    def test_chain_follows_reply_order_not_page_order(self):
        decoded = decoded_chain()
        # scramble insertion order — chain order must still be root → child1 → child2
        reordered = {fx.CHILD2_ID: decoded[fx.CHILD2_ID],
                     fx.CHILD1_ID: decoded[fx.CHILD1_ID],
                     fx.ROOT_ID: decoded[fx.ROOT_ID]}
        with patch("time.sleep"):
            chain, _ = m.reconstruct_thread(fx.ROOT_ID, reordered, lambda tid: None)
        self.assertEqual([tw["id"] for tw in chain],
                         [fx.ROOT_ID, fx.CHILD1_ID, fx.CHILD2_ID])


if __name__ == "__main__":
    unittest.main()
