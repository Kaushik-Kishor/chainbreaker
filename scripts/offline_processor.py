#!/usr/bin/env python3
import argparse
import asyncio
import csv
from pathlib import Path

from backend.ingestion.cicflow_parser import parse_network_flow_row, normalize_column_name
from backend.pipeline.orchestrator import Orchestrator
from backend.utils.logger import setup_logger

logger = setup_logger("offline_processor")


async def process_csv(csv_path: str, batch_size: int = 1000, max_rows: int = None):
    orchestrator = Orchestrator()
    await orchestrator.start()
    try:
        total = 0
        batch = []
        with open(csv_path, "r", encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                if max_rows and i >= max_rows:
                    break
                try:
                    flow = parse_network_flow_row(row)
                    batch.append(flow)
                    if len(batch) >= batch_size:
                        await orchestrator.process_batch(batch)
                        total += len(batch)
                        batch = []
                        logger.info("batch_processed | csv=%s | total=%d | rows=%d",
                                    Path(csv_path).name, total, i + 1)
                except Exception as e:
                    logger.error("flow_parse_error | error=%s | row=%d", str(e), i)
            if batch:
                await orchestrator.process_batch(batch)
                total += len(batch)
                logger.info("final_batch_processed | csv=%s | total=%d",
                            Path(csv_path).name, total)
        logger.info("offline_processing_complete | csv=%s | total_flows=%d", csv_path, total)
    finally:
        await orchestrator.stop()


def get_dataset_files(data_dir: Path) -> list[Path]:
    """Return ordered list of CICIoT2023 CSVs: train, validation, test."""
    known_paths = [
        data_dir / "train"      / "train.csv",
        data_dir / "validation" / "validation.csv",
        data_dir / "test"       / "test.csv",
    ]
    return [p for p in known_paths if p.exists()]


async def process_all_datasets(data_dir: Path, batch_size: int = 1000, max_per_file: int = None):
    csv_files = get_dataset_files(data_dir)
    if not csv_files:
        logger.warning("no_dataset_files_found | dir=%s", str(data_dir))
        return
    
    for csv_path in csv_files:
        logger.info("processing_dataset | path=%s", str(csv_path))
        await process_csv(str(csv_path), batch_size, max_per_file)


async def main():
    parser = argparse.ArgumentParser(description="Offline CSV processor for ChainBreaker")
    parser.add_argument("--csv", type=str, help="Path to single CSV file")
    parser.add_argument("--batch-size", type=int, default=1000, help="Batch size for processing")
    parser.add_argument("--max-rows", type=int, help="Max rows per file to process")
    args = parser.parse_args()
    
    if args.csv:
        await process_csv(args.csv, args.batch_size, args.max_rows)
    else:
        data_dir = Path(__file__).parent.parent / "data"
        await process_all_datasets(data_dir, args.batch_size, args.max_rows)


if __name__ == "__main__":
    asyncio.run(main())