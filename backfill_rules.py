import sys
import time
import logging
import os
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# Setup logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s [%(levelname)s] %(message)s',
                    handlers=[
                        logging.StreamHandler(sys.stdout),
                        logging.FileHandler(ROOT / "storage" / "backfill_rules.log", encoding="utf-8")
                    ])
logger = logging.getLogger("backfill_rules")

from storage.metadata_db import (
    Path as DBPath,
    _connect,
    save_engineering_rule,
    delete_engineering_rules
)
from storage.rules_extractor import StructuredRulesExtractor


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
    
    target_files = [(path, name) for path, name in normative_files if path not in files_with_rules]
    
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
        
        # Load chunks for this file
        with _connect(db_path) as conn:
            c = conn.cursor()
            c.execute("SELECT parent_id, parent_text FROM parent_chunks WHERE source_path = ?", (source_path,))
            chunks = c.fetchall()
            
        logger.info(f"Found {len(chunks)} chunks for this file.")
        
        # Clear any partial rules to prevent duplicates
        delete_engineering_rules(db_path, source_path)
        
        file_rules_count = 0
        for chunk_idx, (parent_id, parent_text) in enumerate(chunks, 1):
            if not any(char.isdigit() for char in parent_text):
                continue # Skip chunks without any digits
                
            try:
                # Extract rules (this calls OpenRouter or custom provider)
                rules = extractor.extract_rules(
                    text=parent_text, 
                    document_id="backfill", 
                    file_key=source_path, 
                    chunk_id=parent_id
                )
                
                if rules:
                    for r in rules:
                        save_engineering_rule(
                            db_path=db_path,
                            source_path=source_path,
                            chunk_id=parent_id,
                            rule_text=parent_text,
                            subject=r.get("subject"),
                            parameter=r.get("parameter"),
                            operator=r.get("operator"),
                            value=r.get("value"),
                            unit=r.get("unit"),
                            condition=r.get("condition")
                        )
                    file_rules_count += len(rules)
            except Exception as e:
                logger.error(f"Error processing chunk {parent_id}: {e}")
                
        duration = time.time() - t_start
        logger.info(f"Finished file {file_name}: Extracted {file_rules_count} rules in {duration:.1f}s")
        success_count += 1
        
    logger.info(f"Backfill finished. Successfully processed {success_count} files.")

if __name__ == '__main__':
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
