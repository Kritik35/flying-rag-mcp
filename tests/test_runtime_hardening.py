import asyncio
import importlib
import logging
import os
import sys
import unittest
import sqlite3
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch


class RuntimeHardeningTests(unittest.TestCase):
    def test_imports_and_constructors_preserve_proxy_environment(self):
        original = {"NO_PROXY": "corp.example", "no_proxy": "corp.example"}
        with patch.dict(os.environ, original, clear=False):
            sys.modules.pop("embedder.client", None)
            module = importlib.import_module("embedder.client")
            with patch("pathlib.Path.exists", return_value=False):
                from storage.rules_extractor import StructuredRulesExtractor
                StructuredRulesExtractor()
            self.assertEqual(os.environ["NO_PROXY"], original["NO_PROXY"])
            self.assertEqual(os.environ["no_proxy"], original["no_proxy"])
            self.assertEqual(module._httpx_client_kwargs("http://localhost:13305/api/v1"), {"trust_env": False})
            self.assertEqual(module._httpx_client_kwargs("https://example.com/api"), {})

    def test_cache_scope_includes_corpus_generation(self):
        from rag_server.tools import build_search_scope_key
        first = build_search_scope_key(None, None, .7, "model", corpus_generation="gen-1")
        second = build_search_scope_key(None, None, .7, "model", corpus_generation="gen-2")
        self.assertNotEqual(first, second)
        self.assertIn("gen-1", first)

    def test_metadata_generation_bumps_after_successful_upsert_and_delete(self):
        from storage.metadata_db import delete_file, get_corpus_generation, init_db, upsert_file
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "metadata.db"
            init_db(db)
            self.assertEqual(get_corpus_generation(db), 0)
            upsert_file(db, "fixture", "fixture.pdf", "pdf", "sha", "c", "m", 1)
            self.assertEqual(get_corpus_generation(db), 1)
            delete_file(db, "fixture")
            self.assertEqual(get_corpus_generation(db), 2)

    def test_failed_upsert_does_not_bump_generation(self):
        from storage.metadata_db import get_corpus_generation, init_db, upsert_file
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "metadata.db"
            init_db(db)
            with self.assertRaises(sqlite3.IntegrityError):
                upsert_file(db, "fixture", None, "pdf", "sha", "c", "m", 1)
            self.assertEqual(get_corpus_generation(db), 0)

    def test_generation_bumps_only_for_effective_deprecation_and_delete(self):
        from storage.metadata_db import (
            delete_file, get_corpus_generation, init_db, mark_deprecated, upsert_file,
        )
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "metadata.db"
            init_db(db)
            upsert_file(db, "fixture", "fixture.pdf", "pdf", "sha", "c", "m", 1)
            mark_deprecated(db, "fixture")
            self.assertEqual(get_corpus_generation(db), 2)
            mark_deprecated(db, "fixture")
            delete_file(db, "missing")
            self.assertEqual(get_corpus_generation(db), 2)
            delete_file(db, "fixture")
            self.assertEqual(get_corpus_generation(db), 3)

    def test_semantic_cache_separates_generations_in_temporary_database(self):
        from storage.semantic_cache import SemanticCache
        with TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "cache.db")
            first = SemanticCache(db_path=db_path, corpus_generation="gen-1")
            second = SemanticCache(db_path=db_path, corpus_generation="gen-2")
            first.store("query", [1.0, 0.0], [{"text": "old"}])
            self.assertIsNone(second.lookup("query", [1.0, 0.0]))

    def test_mcp_exception_is_redacted(self):
        from rag_server import server
        secret = str(Path.cwd() / "private" / "document.pdf")
        with patch.object(server, "_dispatch", side_effect=RuntimeError(secret)):
            result = asyncio.run(server.handle_call_tool("search_documents", {}))
        self.assertNotIn(secret, result[0].text)
        self.assertIn("internal_error", result[0].text)

    def test_successful_public_result_preserves_documented_path_fields(self):
        from rag_server.server import _safe_result
        secret = str(Path.cwd() / "private" / "document.pdf")
        result = _safe_result({
            "status": "success", "source_path": secret,
            "path": secret, "log_path": secret,
        })
        self.assertEqual(result["source_path"], secret)
        self.assertEqual(result["path"], secret)
        self.assertEqual(result["log_path"], secret)

    def test_diagnostic_payload_sanitizes_path_fields(self):
        from rag_server.server import _safe_result
        secret = str(Path.cwd() / "private" / "diagnostic.log")
        for status in ("error", "failed", "partial"):
            result = _safe_result({"status": status, "log_path": secret})
            self.assertEqual(result["log_path"], "diagnostic.log")
        result = _safe_result({"error": "provider failed", "source_path": secret})
        self.assertEqual(result["source_path"], "diagnostic.log")

    def test_reindex_status_like_payload_redacts_paths_inside_arbitrary_strings(self):
        from rag_server.server import _safe_result
        secret = str(Path.cwd() / "private logs" / "reindex secret.log")
        result = _safe_result({"jobs": [{
            "status": "failed", "path": secret,
            "error": f"failed while opening {secret}",
        }]})
        self.assertEqual(result["jobs"][0]["path"], "reindex secret.log")
        self.assertEqual(result["jobs"][0]["error"], "internal_error")

    def test_sanitizer_preserves_urls_and_trailing_prose(self):
        from rag_server.server import _safe_result
        url = "https://example.com/api/v1/documents"
        message = r"failed at C:\Private Files\report.pdf while indexing continued"
        result = _safe_result({"status": "error", "url": url, "message": message})
        self.assertEqual(result["url"], url)
        self.assertEqual(result["message"], "internal_error")
        note = _safe_result({"note": message})
        self.assertEqual(note["note"], "failed at [redacted-path] while indexing continued")

    def test_sanitizer_redacts_absolute_directory_and_unc_messages(self):
        from rag_server.server import _safe_result
        result = _safe_result({
            "status": "error",
            "message": r"failed at C:\Private Files\Corpus Directory while indexing continued",
            "detail": r"failed at \\fileserver\secret share\Corpus during status refresh",
        })
        self.assertEqual(result["message"], "internal_error")
        self.assertEqual(result["detail"], "internal_error")

    def test_diagnostic_unix_directory_fails_closed_but_url_does_not(self):
        from rag_server.server import _safe_result
        result = _safe_result({
            "status": "error",
            "debug": "failed under /srv/private corpus while refreshing",
            "message": "provider https://example.com/api/v1 unavailable",
        })
        self.assertEqual(result["debug"], "internal_error")
        self.assertEqual(result["message"], "provider https://example.com/api/v1 unavailable")

    def test_empty_diagnostic_fields_are_not_reported_as_an_error(self):
        """An absent error is information too — and it was being destroyed.

        The trace carries `parent_hydration.error: ""` on a healthy search. The
        sanitizer replaced the value of every key named `error` unconditionally,
        so a clean run reached the client as `internal_error` and every single
        search looked broken.
        """
        from rag_server.server import _safe_result

        result = _safe_result({"retrieval": {"parent_hydration": {
            "hydrated": 60, "fell_back_to_child": 0, "error": "",
        }}})
        self.assertEqual(result["retrieval"]["parent_hydration"]["error"], "")

    def test_a_real_error_is_still_redacted(self):
        from rag_server.server import _safe_result
        secret = str(Path.cwd() / "private" / "metadata.db")

        result = _safe_result({"parent_hydration": {"error": f"db not found: {secret}"}})
        self.assertEqual(result["parent_hydration"]["error"], "internal_error")

    def test_rules_extractor_scopes_proxy_only_for_localhost(self):
        from storage.rules_extractor import _provider_http_kwargs
        local = _provider_http_kwargs("http://localhost:13305/api/v1")
        self.assertFalse(local["http_client"]._trust_env)
        local["http_client"].close()
        self.assertEqual(_provider_http_kwargs("https://openrouter.ai/api/v1"), {})

    def test_backfill_logging_is_cli_only_and_bounded(self):
        named = logging.getLogger("backfill_rules")
        before = list(named.handlers)
        sys.modules.pop("backfill_rules", None)
        module = importlib.import_module("backfill_rules")
        self.assertEqual(named.handlers, before)
        with TemporaryDirectory() as tmp:
            handlers = module.configure_logging(Path(tmp) / "backfill.log")
            self.assertEqual(len(handlers), 2)
            rotating = [h for h in handlers if hasattr(h, "maxBytes")]
            self.assertEqual(len(rotating), 1)
            self.assertGreater(rotating[0].maxBytes, 0)
            self.assertGreater(rotating[0].backupCount, 0)
            self.assertEqual(named.handlers, handlers)
            self.assertFalse(named.propagate)
            self.assertIs(module.configure_logging(Path(tmp) / "backfill.log"), handlers)
            for handler in handlers:
                handler.close()
            named.handlers.clear()
            del named._flying_rag_configured_handlers


if __name__ == "__main__":
    unittest.main()
