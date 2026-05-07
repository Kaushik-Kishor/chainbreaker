"""
train_ml.py — Entry point for training the NIDS ML models on CICIoT2023.

Run from project root:
    python scripts/train_ml.py

Optional flags:
    --train  PATH       Path to training CSV   [default: data/train/train.csv]
    --val    PATH       Path to validation CSV [default: data/validation/validation.csv]
    --outdir DIR        Model output dir       [default: models/]
    --chunksize N       Rows per chunk         [default: 200000]
    --max-rows N        Dev mode row cap       [default: 0 = all]
    --test-size FLOAT   Internal test split    [default: 0.2]
    --contamination F   IsoForest param        [default: 0.05]

Example (dev / smoke-test on 200k rows):
    python scripts/train_ml.py --max-rows 200000 --chunksize 100000
"""

import sys
import os

# Ensure project root is on the path so 'backend' is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.ml.train import _parse_args, train_pipeline  # noqa: E402

if __name__ == "__main__":
    args = _parse_args()
    csv_paths = [args.train]
    if args.val and os.path.exists(args.val):
        csv_paths.append(args.val)
    train_pipeline(
        csv_paths=csv_paths,
        outdir=args.outdir,
        chunksize=args.chunksize,
        max_rows=args.max_rows,
        test_size=args.test_size,
        contamination=args.contamination,
    )
