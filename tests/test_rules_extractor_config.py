from __future__ import annotations

import unittest


class RulesExtractorConfigTests(unittest.TestCase):
    def test_model_id_exposes_primary_configured_model_for_compatibility(self):
        from storage.rules_extractor import StructuredRulesExtractor

        extractor = StructuredRulesExtractor()

        self.assertEqual(extractor.model_id, extractor.models[0])


if __name__ == "__main__":
    unittest.main()
