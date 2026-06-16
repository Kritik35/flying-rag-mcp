from __future__ import annotations
import os
import uuid
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class StructuredRulesExtractor:
    def __init__(self):
        import os
        import yaml
        from pathlib import Path
        
        os.environ["NO_PROXY"] = "*"
        os.environ["no_proxy"] = "*"
        
        # Default fallback settings with OpenRouter free models
        self.enabled = True
        self.model_url = "https://openrouter.ai/api/v1"
        self.models = [
            "nvidia/nemotron-3-ultra-550b-a55b:free",
            "nvidia/nemotron-3-super-120b-a12b:free",
            "openai/gpt-oss-120b:free",
            "qwen/qwen3-next-80b-a3b-instruct:free",
            "qwen/qwen3-coder:free",
            "meta-llama/llama-3.3-70b-instruct:free",
            "nousresearch/hermes-3-405b:free",
            "qwen/qwen-2.5-coder-32b-instruct:free",
            "google/gemma-2-9b-it:free",
            "meta-llama/llama-3.2-3b-instruct:free"
        ]
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        self.max_workers = 1
        
        # Try loading configuration
        config_path = Path(__file__).parent.parent / "config.yaml"
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
                    re_cfg = cfg.get("rules_extraction", {})
                    if re_cfg:
                        self.enabled = bool(re_cfg.get("enabled", True))
                        self.model_url = re_cfg.get("model_url", self.model_url)
                        self.api_key = re_cfg.get("api_key", self.api_key)
                        self.max_workers = int(re_cfg.get("max_workers", 1))
                        
                        # Load models list if available
                        cfg_models = re_cfg.get("models")
                        if cfg_models:
                            if isinstance(cfg_models, list):
                                self.models = cfg_models
                            elif isinstance(cfg_models, str):
                                self.models = [cfg_models]
                        elif re_cfg.get("model_id"):
                            self.models = [re_cfg.get("model_id")]
            except Exception as e:
                logger.error(f"[EXTRACTOR] Error loading config.yaml: {e}")
                
        # Load from project-local .env if API key still missing
        if not self.api_key:
            env_path = Path(__file__).parent.parent / ".env"
            if env_path.exists():
                try:
                    with open(env_path, "r", encoding="utf-8") as f:
                        for line in f:
                            if line.strip().startswith("OPENROUTER_API_KEY="):
                                self.api_key = line.strip().split("=", 1)[1].strip()
                                break
                except Exception as e:
                    logger.error(f"[EXTRACTOR] Error reading env file: {e}")

    def extract_rules(self, text: str, document_id: str, file_key: str, chunk_id: str) -> List[Dict[str, Any]]:
        if not text or not text.strip():
            return []
        if not any(c.isdigit() for c in text):
            return []

        import re
        import sys
        # Pre-process text to replace Russian decimal commas with dots (e.g. '0,4' -> '0.4')
        text = re.sub(r'(\d),(\d)', r'\1.\2', text)

        try:
            import langextract as lx
        except ImportError:
            logger.warning("[EXTRACTOR] langextract not installed. Skipping rule extraction.")
            return []

        prompt = (
            "Extract structured engineering compliance rules from the provided text. "
            "For each rule, locate the exact text matches in the source text. "
            "Verify that the extracted values are mathematically correct and correspond directly to the source text."
        )

        from langextract.data import ExampleData, Extraction
        example_extraction_1 = Extraction(
            extraction_class="EngineeringRule",
            extraction_text="1.2 м",
            attributes={
                "subject": "ширина путей эвакуации",
                "parameter": "ширина",
                "operator": ">=",
                "value": "1.2",
                "unit": "м",
                "condition": "при числе людей более 15"
            }
        )
        example_extraction_2 = Extraction(
            extraction_class="EngineeringRule",
            extraction_text="менее 0.4 сносящих скоростей",
            attributes={
                "subject": "скорость потока",
                "parameter": "скорость",
                "operator": "<",
                "value": "0.4",
                "unit": "м/с",
                "condition": "для рыб наименьшего защищаемого размера"
            }
        )
        examples = [
            ExampleData(
                text="Ширина путей эвакуации из помещений должна быть не менее 1.2 м при числе людей более 15.",
                extractions=[example_extraction_1]
            ),
            ExampleData(
                text="Зона водного объекта, где скорости потока, направленного в гидротехническое сооружение, менее 0.4 сносящих скоростей для рыб наименьшего защищаемого размера.",
                extractions=[example_extraction_2]
            )
        ]

        if not self.enabled:
            logger.info("[EXTRACTOR] Rules extraction is disabled in configuration.")
            return []

        if not self.api_key:
            self.api_key = os.getenv("OPENROUTER_API_KEY")

        if not self.api_key:
            print("[EXTRACTOR] WARNING: API key not found. Rule extraction skipped.", file=sys.stderr)
            return []

        from langextract import factory
        result = None
        last_error = None

        for model in self.models:
            print(f"[EXTRACTOR] Trying rules extraction with model: {model}", file=sys.stderr)
            try:
                is_google_model = model.startswith("gemini-") or model.startswith("gemma-")
                is_google_key = self.api_key and (self.api_key.startswith("AIzaSy") or self.api_key.startswith("AQ."))
                use_native_gemini = is_google_model and is_google_key

                p_kwargs = {
                    "api_key": self.api_key,
                    "temperature": 0.0,
                    "timeout": 120.0
                }
                if use_native_gemini:
                    from google.genai.types import HttpOptions
                    p_kwargs["http_options"] = HttpOptions(timeout=120000.0)
                else:
                    p_kwargs["base_url"] = self.model_url
                    p_kwargs["max_retries"] = 0

                config_obj = factory.ModelConfig(
                    model_id=model,
                    provider="gemini" if use_native_gemini else "openai",
                    provider_kwargs=p_kwargs
                )
                result = lx.extract(
                    text,
                    prompt_description=prompt,
                    examples=examples,
                    config=config_obj
                )
                # Success
                break
            except Exception as e:
                last_error = e
                print(f"[EXTRACTOR] Error with model {model}: {e}. Trying fallback...", file=sys.stderr)
                continue

        if result is None:
            print(f"[EXTRACTOR] All models failed. Last error: {last_error}", file=sys.stderr)
            return []

        try:
            rules = []
            extractions = []
            if hasattr(result, "extractions") and result.extractions:
                extractions = result.extractions
            elif isinstance(result, list) and len(result) > 0 and hasattr(result[0], "extractions"):
                extractions = result[0].extractions

            for ext in extractions:
                attrs = ext.attributes or {}
                try:
                    val = float(attrs.get("value", 0.0))
                except (ValueError, TypeError):
                    val = 0.0

                rules.append({
                    "id": str(uuid.uuid4()),
                    "document_id": document_id,
                    "file_key": file_key,
                    "chunk_id": chunk_id,
                    "subject": attrs.get("subject", "N/A"),
                    "parameter": attrs.get("parameter", "N/A"),
                    "operator": attrs.get("operator", "N/A"),
                    "value": val,
                    "unit": attrs.get("unit", "N/A"),
                    "condition": attrs.get("condition", None)
                })
            return rules

        except Exception as e:
            logger.error(f"[EXTRACTOR] Error processing rules extraction result: {e}", exc_info=True)
            return []

