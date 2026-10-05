"""An external visual backend runs only with explicit consent.

With colpali.enabled and backend: api, every PDF the indexer touched had its
pages rendered and sent to the provider — project drawings included. What kept
them in was an HTTP 451 from the provider, not the server. Sending documents
to a third party is now a setting of its own, colpali.allow_external, and
without it nothing leaves the machine.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from embedder import colpali


def _boom(*_a, **_kw):
    raise AssertionError("a request to the external provider was made")


class ConsentTests(unittest.TestCase):
    API = {"enabled": True, "backend": "api", "api_provider": "jina",
           "late_interaction": True, "api_key": "test"}

    def _with(self, cfg):
        return mock.patch.object(colpali, "_cfg", return_value=cfg)

    def test_indexing_sends_nothing_without_consent(self):
        with self._with(dict(self.API)), \
                mock.patch.object(colpali, "_render_pages", side_effect=_boom), \
                mock.patch.object(colpali, "_jina_multivec", side_effect=_boom), \
                mock.patch.object(colpali, "_jina_embed", side_effect=_boom):
            self.assertEqual(colpali.maybe_index_visual(Path("drawing.pdf")), 0)

    def test_visual_search_sends_nothing_without_consent(self):
        with self._with(dict(self.API)), \
                mock.patch.object(colpali, "_jina_multivec", side_effect=_boom), \
                mock.patch.object(colpali, "_jina_embed", side_effect=_boom):
            self.assertEqual(colpali.search_visual("план вентиляции"), [])
        self.assertIn("allow_external", colpali.LAST_ERROR or "")

    def test_consent_lets_the_external_backend_run(self):
        cfg = dict(self.API, allow_external=True)
        with self._with(cfg):
            self.assertTrue(colpali.external_allowed(cfg))

    def test_a_local_backend_needs_no_consent(self):
        self.assertTrue(colpali.external_allowed({"backend": "local"}))


class DrawingsToolSaysWhyTests(unittest.TestCase):
    def test_a_refused_channel_is_not_reported_as_no_hits(self):
        from rag_server import tools

        with mock.patch.object(colpali, "_cfg", return_value=dict(ConsentTests.API)):
            result = tools.search_drawings("план вентиляции", top_k=1)
        self.assertEqual(result["results"], [])
        self.assertIn("allow_external", result.get("unavailable", ""))


class BackendNameTests(unittest.TestCase):
    """YAML reads a bare `off` as False; that must not count as a backend."""

    def test_a_boolean_off_is_off(self):
        from config_loader import backend_name

        self.assertEqual(backend_name({"backend": False}), "off")
        self.assertEqual(backend_name({}), "off")
        self.assertEqual(backend_name({"backend": " API "}), "api")

    def test_hyde_stays_off_when_enabled_with_backend_off(self):
        from rag_server import hyde

        with mock.patch.object(hyde, "_hyde_cfg",
                               return_value={"enabled": True, "backend": False}):
            self.assertFalse(hyde.is_enabled())


if __name__ == "__main__":
    unittest.main()
