import sys
import types
import unittest
from unittest.mock import patch

from storage.rules_extractor import RulesExtractionError, StructuredRulesExtractor


class RulesExtractorFailureTests(unittest.TestCase):
    def extractor(self):
        obj = StructuredRulesExtractor.__new__(StructuredRulesExtractor)
        obj.enabled = True
        obj.api_key = "key"
        obj.model_url = "https://provider.invalid/v1"
        obj.models = ["model"]
        return obj

    def modules(self, extract):
        lx = types.ModuleType("langextract")
        lx.factory = types.SimpleNamespace(ModelConfig=lambda **kwargs: kwargs)
        lx.extract = extract
        data = types.ModuleType("langextract.data")
        data.ExampleData = lambda **kwargs: kwargs
        data.Extraction = lambda **kwargs: types.SimpleNamespace(**kwargs)
        return {"langextract": lx, "langextract.data": data}

    def test_legacy_all_provider_failure_returns_empty(self):
        with patch.dict("sys.modules", self.modules(lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))):
            self.assertEqual([], self.extractor().extract_rules("Limit 10", "d", "f", "c"))

    def test_strict_all_provider_failure_raises(self):
        with patch.dict("sys.modules", self.modules(lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))):
            with self.assertRaises(RulesExtractionError):
                self.extractor().extract_rules("Limit 10", "d", "f", "c", raise_on_failure=True)

    def test_strict_missing_api_key_raises(self):
        ext = self.extractor(); ext.api_key = None
        with patch.dict("os.environ", {}, clear=True), patch.dict("sys.modules", self.modules(lambda *a, **k: None)):
            with self.assertRaises(RulesExtractionError):
                ext.extract_rules("Limit 10", "d", "f", "c", raise_on_failure=True)

    def test_successful_empty_result_is_valid_zero_in_strict_mode(self):
        result = types.SimpleNamespace(extractions=[])
        with patch.dict("sys.modules", self.modules(lambda *a, **k: result)):
            self.assertEqual([], self.extractor().extract_rules("Limit 10", "d", "f", "c", raise_on_failure=True))

    def test_strict_malformed_result_processing_raises(self):
        class BadExtraction:
            @property
            def attributes(self):
                raise ValueError("malformed")
        bad = types.SimpleNamespace(extractions=[BadExtraction()])
        with patch.dict("sys.modules", self.modules(lambda *a, **k: bad)):
            with self.assertRaises(RulesExtractionError):
                self.extractor().extract_rules("Limit 10", "d", "f", "c", raise_on_failure=True)

    def test_strict_missing_langextract_raises(self):
        ext = self.extractor()
        real_import = __import__
        def blocked(name, *args, **kwargs):
            if name == "langextract": raise ImportError("missing")
            return real_import(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=blocked):
            with self.assertRaises(RulesExtractionError):
                ext.extract_rules("Limit 10", "d", "f", "c", raise_on_failure=True)

    def test_strict_invalid_numeric_value_raises(self):
        result = types.SimpleNamespace(extractions=[types.SimpleNamespace(attributes={"value": "not-a-number"})])
        with patch.dict("sys.modules", self.modules(lambda *a, **k: result)):
            with self.assertRaises(RulesExtractionError):
                self.extractor().extract_rules("Limit 10", "d", "f", "c", raise_on_failure=True)

    def test_legacy_invalid_numeric_value_remains_zero(self):
        result = types.SimpleNamespace(extractions=[types.SimpleNamespace(attributes={"value": "not-a-number"})])
        with patch.dict("sys.modules", self.modules(lambda *a, **k: result)):
            rules = self.extractor().extract_rules("Limit 10", "d", "f", "c")
        self.assertEqual(0.0, rules[0]["value"])

    def test_strict_numeric_zero_is_valid(self):
        for value in (0, "0"):
            with self.subTest(value=value):
                result = types.SimpleNamespace(extractions=[types.SimpleNamespace(attributes={"value": value})])
                with patch.dict("sys.modules", self.modules(lambda *a, **k: result)):
                    rules = self.extractor().extract_rules("Limit 10", "d", "f", "c", raise_on_failure=True)
                self.assertEqual(0.0, rules[0]["value"])


if __name__ == "__main__":
    unittest.main()
