from __future__ import annotations

import unittest


class TopKIsHonouredTests(unittest.TestCase):
    """Source concentration filtered the answer after it had been cut to top_k.

    Applied to a list that was already truncated it can only remove, never add,
    so 15 of 16 measured queries came back short — 3.44 results for a requested
    5. Concentration still decides the order; what it drops is refilled from the
    retrieval pool rather than leaving the caller with less than it asked for.
    """

    def test_concentration_never_returns_less_than_requested(self):
        from rag_server.tools import fill_to_top_k

        pool = [{"chunk_id": f"c{i}", "file_name": f"doc{i}.pdf"} for i in range(10)]
        focused = pool[:2]

        final = fill_to_top_k(focused, pool, top_k=5)

        self.assertEqual(len(final), 5)
        self.assertEqual([c["chunk_id"] for c in final[:2]], ["c0", "c1"])

    def test_the_focused_head_keeps_its_order(self):
        from rag_server.tools import fill_to_top_k

        pool = [{"chunk_id": f"c{i}"} for i in range(6)]
        focused = [pool[3], pool[1]]

        final = fill_to_top_k(focused, pool, top_k=4)

        self.assertEqual([c["chunk_id"] for c in final], ["c3", "c1", "c0", "c2"])

    def test_nothing_is_duplicated_when_filling(self):
        from rag_server.tools import fill_to_top_k

        pool = [{"chunk_id": f"c{i}"} for i in range(4)]
        final = fill_to_top_k(pool[:2], pool, top_k=10)

        self.assertEqual(len(final), 4)
        self.assertEqual(len({c["chunk_id"] for c in final}), 4)

    def test_a_short_pool_is_not_padded_with_nothing(self):
        from rag_server.tools import fill_to_top_k

        pool = [{"chunk_id": "c0"}]
        self.assertEqual(len(fill_to_top_k(pool, pool, top_k=5)), 1)


class SubqueryPoolTests(unittest.TestCase):
    """The per-subquery budget was divided by (n - 1) subqueries.

    Recall per subquery therefore fell as the query plan got richer, which is
    backwards: RRF needs each list deep enough to have something to fuse.
    """

    def test_depth_does_not_shrink_as_the_plan_grows(self):
        from rag_server.tools import subquery_pool_size

        depths = [subquery_pool_size(40, n) for n in (1, 2, 3, 5, 8)]
        self.assertEqual(depths, sorted(depths), "depth must never fall as subqueries grow")

    def test_a_single_subquery_gets_the_whole_budget(self):
        from rag_server.tools import subquery_pool_size

        self.assertGreaterEqual(subquery_pool_size(40, 1), 40)

    def test_there_is_always_a_usable_floor(self):
        from rag_server.tools import subquery_pool_size

        self.assertGreaterEqual(subquery_pool_size(1, 5), 24)


if __name__ == "__main__":
    unittest.main()
