from __future__ import annotations

import unittest
from pathlib import Path

import yaml


class ConfigExampleTests(unittest.TestCase):
    def test_example_uses_lemonade_router_port_13305(self):
        cfg = yaml.safe_load(Path("config.example.yaml").read_text(encoding="utf-8"))

        self.assertEqual(cfg["lemonade"]["base_url"], "http://localhost:13305/api/v1")
        self.assertEqual(
            cfg["retrieval"]["rerank_endpoint"],
            "http://localhost:13305/api/v1/reranking",
        )


if __name__ == "__main__":
    unittest.main()
