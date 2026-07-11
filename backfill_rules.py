import sys
import time
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

logger = logging.getLogger("backfill_rules")


def configure_logging(log_path: Path = ROOT / "storage" / "backfill_rules.log"):
    configured = getattr(logger, "_flying_rag_configured_handlers", None)
    if configured and all(handler in logger.handlers for handler in configured):
        return configured
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handlers = [
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(
            log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        ),
    ]
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    for handler in handlers:
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger._flying_rag_configured_handlers = handlers
    return handlers

from storage.metadata_db import (
    _connect,
    replace_engineering_rules
)
from storage.rules_extractor import StructuredRulesExtractor


def backfill_file(db_path: Path, source_path: str, extractor) -> dict:
    """Safely replace one explicitly requested file after complete extraction."""
    with _connect(db_path) as conn:
        chunks = conn.execute(
            """SELECT parent_id, parent_text FROM parent_chunks
               WHERE source_path = ? ORDER BY parent_id""",
            (source_path,),
        ).fetchall()

    pending_rules = []
    processed_chunks = 0
    for parent_id, parent_text in chunks:
        if not any(char.isdigit() for char in parent_text):
            continue
        try:
            extracted = extractor.extract_rules(
                text=parent_text, document_id="backfill",
                file_key=source_path, chunk_id=parent_id,
            ) or []
        except Exception as exc:
            return {
                "status": "partial" if processed_chunks else "failed",
                "processed_chunks": processed_chunks,
                "rule_count": len(pending_rules),
                "error": str(exc),
            }
        processed_chunks += 1
        for rule in extracted:
            pending_rules.append({
                **rule, "chunk_id": parent_id, "rule_text": parent_text,
            })

    try:
        replace_engineering_rules(db_path, source_path, pending_rules)
    except Exception as exc:
        return {
            "status": "failed", "processed_chunks": processed_chunks,
            "rule_count": len(pending_rules), "error": str(exc),
        }
    return {
        "status": "success", "processed_chunks": processed_chunks,
        "rule_count": len(pending_rules), "error": None,
    }


def _select_missing_files(normative_files, files_with_rules):
    """Keep production backfill missing-only; refresh is an explicit operation."""
    return [item for item in normative_files if item[0] not in files_with_rules]


def _resolve_api_key(api_key: str | None, api_key_env: str | None, api_key_file: str | None) -> str | None:
    """Resolve provider key without requiring the secret in the process argv."""
    if api_key:
        return api_key
    if api_key_env:
        return os.getenv(api_key_env)
    if api_key_file:
        try:
            return Path(api_key_file).read_text(encoding="utf-8").strip()
        except OSError as e:
            logger.error(f"Failed to read API key file {api_key_file}: {e}")
            return None
    return None


def run_backfill(limit_files: int = None, modulo: int = 1, remainder: int = 0, 
                 api_key: str = None, base_url: str = None, models: list = None):
    db_path = ROOT / "data" / "metadata.db"
    
    logger.info("Initializing Rules Extractor...")
    extractor = StructuredRulesExtractor()
    
    if api_key:
        extractor.api_key = api_key
        logger.info("Using custom API key from command line args.")
    if base_url:
        extractor.model_url = base_url
        logger.info(f"Using custom model URL: {base_url}")
    if models:
        extractor.models = models
        logger.info(f"Using custom models: {models}")
        
    if not extractor.enabled:
        logger.error("Rules extraction is disabled in config.yaml! Please check configuration.")
        return
        
    if not extractor.api_key:
        logger.error("OpenRouter API key is missing! Please set OPENROUTER_API_KEY in .env.")
        return
        
    logger.info(f"Models configured: {extractor.models}")
    
    # Connect to DB to check files
    with _connect(db_path) as conn:
        # Get all normative files
        c = conn.cursor()
        c.execute("SELECT source_path, file_name FROM files WHERE dataset = 'normative'")
        normative_files = c.fetchall()
        
        # Get files that already have rules
        c.execute("SELECT DISTINCT source_path FROM engineering_rules")
        files_with_rules = {row[0] for row in c.fetchall()}
        
    logger.info(f"Total normative files on metadata.db: {len(normative_files)}")
    logger.info(f"Files with rules already: {len(files_with_rules)}")
    
    target_files = _select_missing_files(normative_files, files_with_rules)
    
    # Partition files for parallel runs
    target_files = [f for idx, f in enumerate(target_files) if idx % modulo == remainder]
    logger.info(f"Files to process (without rules, modulo={modulo}, remainder={remainder}): {len(target_files)}")
    
    if limit_files:
        logger.info(f"Limiting execution to first {limit_files} files.")
        target_files = target_files[:limit_files]
        
    if not target_files:
        logger.info("No files require backfill. Exiting.")
        return
        
    success_count = 0
    for idx, (source_path, file_name) in enumerate(target_files, 1):
        logger.info(f"[{idx}/{len(target_files)}] Processing file: {file_name}")
        t_start = time.time()
        
        result = backfill_file(db_path, source_path, extractor)
        file_rules_count = result["rule_count"]
        if result["status"] != "success":
            logger.error(
                f"File {file_name} finished with status={result['status']}: {result['error']}"
            )
            continue
                
        duration = time.time() - t_start
        logger.info(f"Finished file {file_name}: Extracted {file_rules_count} rules in {duration:.1f}s")
        success_count += 1
        
    logger.info(f"Backfill finished. Successfully processed {success_count} files.")

if __name__ == '__main__':
    configure_logging()
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10000, help="Limit the number of files to process")
    parser.add_argument("--modulo", type=int, default=1, help="Modulo factor for parallel processing")
    parser.add_argument("--remainder", type=int, default=0, help="Remainder factor for parallel processing")
    parser.add_argument("--api-key", type=str, default=None, help="Custom API key (unsafe: visible in process list)")
    parser.add_argument("--api-key-env", type=str, default=None, help="Read API key from this environment variable")
    parser.add_argument("--api-key-file", type=str, default=None, help="Read API key from this UTF-8 text file")
    parser.add_argument("--base-url", type=str, default=None, help="Custom model base URL")
    parser.add_argument("--models", type=str, default=None, help="Comma-separated models list")
    args = parser.parse_args()
    
    models_list = [m.strip() for m in args.models.split(",")] if args.models else None
    resolved_api_key = _resolve_api_key(args.api_key, args.api_key_env, args.api_key_file)
    
    run_backfill(
        limit_files=args.limit,
        modulo=args.modulo,
        remainder=args.remainder,
        api_key=resolved_api_key,
        base_url=args.base_url,
        models=models_list
    )
