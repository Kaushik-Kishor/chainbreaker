"""
train.py — XGBoost + Isolation Forest training pipeline.

Usage (via scripts/train_ml.py entrypoint):
    python scripts/train_ml.py

Direct:
    python -m backend.ml.train \\
        --train  data/train/train.csv \\
        --val    data/validation/validation.csv \\
        --outdir models/ \\
        --chunksize 200000 \\
        --max-rows 0
"""

from __future__ import annotations

import argparse
import logging
import os
import pickle
import time
import warnings
import json
import datetime
import matplotlib.pyplot as plt
from pathlib import Path
from typing import Iterator

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    f1_score,
)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.utils.class_weight import compute_sample_weight
import xgboost as xgb

from backend.ml.features import (
    BENIGN_LABEL,
    DROP_COLUMNS,
    FEATURE_COLUMNS,
    TARGET_COLUMN,
    normalize_label,
)

warnings.filterwarnings("ignore", category=UserWarning)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ── Data loading ──────────────────────────────────────────────────────────────

_ENCODINGS = ["utf-8", "utf-8-sig", "utf-16", "utf-16le", "latin1", "cp1252"]


def _iter_chunks(path: str, chunksize: int) -> Iterator[pd.DataFrame]:
    """Yield cleaned chunks from a CSV file, trying multiple encodings."""
    encoding_used: str | None = None
    for enc in _ENCODINGS:
        try:
            # Probe by reading first chunk only
            probe = pd.read_csv(path, encoding=enc, nrows=5, low_memory=False)
            encoding_used = enc
            log.info("Detected encoding '%s' for %s", enc, path)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
        except Exception:
            break

    if encoding_used is None:
        raise RuntimeError(f"Cannot decode '{path}' with any of {_ENCODINGS}")

    reader = pd.read_csv(
        path,
        encoding=encoding_used,
        chunksize=chunksize,
        low_memory=False,
        dtype={TARGET_COLUMN: str},
    )
    for chunk in reader:
        yield chunk


def load_dataset(
    csv_paths: list[str],
    chunksize: int = 200_000,
    max_rows: int = 0,
) -> pd.DataFrame:
    """
    Load one or more CSV files in chunks and return a single DataFrame.

    Args:
        csv_paths:  List of file paths (e.g. train.csv, validation.csv).
        chunksize:  Rows per chunk — controls peak RAM usage.
        max_rows:   If > 0, stop after this many total rows (for dev/testing).
                    Set to 0 to load everything.
    """
    frames: list[pd.DataFrame] = []
    total = 0

    for path in csv_paths:
        if not os.path.exists(path):
            log.warning("File not found, skipping: %s", path)
            continue

        log.info("Loading %s ...", path)
        for chunk in _iter_chunks(path, chunksize):
            frames.append(chunk)
            total += len(chunk)
            if max_rows > 0 and total >= max_rows:
                log.info("  Reached max_rows=%d — stopping early.", max_rows)
                break

        if max_rows > 0 and total >= max_rows:
            break

    if not frames:
        raise RuntimeError("No data loaded. Check file paths.")

    df = pd.concat(frames, ignore_index=True)
    log.info("Total rows loaded: %d", len(df))
    return df


# ── Preprocessing ─────────────────────────────────────────────────────────────

def preprocess(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """
    Clean raw DataFrame, extract features and normalized target.

    Returns:
        X: Feature DataFrame (only FEATURE_COLUMNS, no NaNs, all numeric)
        y: Normalized label Series (strings like "BenignTraffic", "ddos", ...)
    """
    # ── Normalize target ──────────────────────────────────────────────────────
    y = df[TARGET_COLUMN].apply(normalize_label)

    # ── Select feature columns (drop missing cols gracefully) ─────────────────
    available = [c for c in FEATURE_COLUMNS if c in df.columns]
    missing = [c for c in FEATURE_COLUMNS if c not in df.columns]
    if missing:
        log.warning("Missing expected columns (will be zero-filled): %s", missing)

    X = df[available].copy()

    # Zero-fill any columns that were in FEATURE_COLUMNS but absent in the file
    for col in missing:
        X[col] = 0.0

    # Reorder to canonical order
    X = X[FEATURE_COLUMNS]

    # ── Coerce all features to float32 ────────────────────────────────────────
    for col in X.columns:
        X[col] = pd.to_numeric(X[col], errors="coerce")

    # Replace inf and fill NaN with 0
    X.replace([np.inf, -np.inf], np.nan, inplace=True)
    X.fillna(0.0, inplace=True)
    X = X.astype(np.float32)

    log.info(
        "Preprocessed: %d rows × %d features | classes: %s",
        len(X),
        len(X.columns),
        y.value_counts().to_dict(),
    )
    return X, y


# ── Training helpers ──────────────────────────────────────────────────────────

def _compute_sample_weights(y_encoded: np.ndarray) -> np.ndarray:
    """Balanced sample weights to compensate for class imbalance."""
    return compute_sample_weight(class_weight="balanced", y=y_encoded)


def train_xgboost(
    X_train: pd.DataFrame,
    y_train_enc: np.ndarray,
    num_classes: int,
    n_jobs: int = -1,
) -> xgb.XGBClassifier:
    """
    Train a multi-class XGBoost classifier.

    Uses sample_weight for balanced training (preferred over SMOTE for
    large tabular datasets — avoids synthetic sample artifacts).

    Falls back to binary:logistic when only one class is present
    (e.g. dev-mode sampling hits only benign rows).
    """
    log.info("Training XGBoost — %d classes, %d samples ...", num_classes, len(X_train))

    sample_weights = _compute_sample_weights(y_train_enc)

    # Guard: XGBoost requires num_class >= 2 for multi:softprob.
    # Fall back to binary when the loaded slice is all-benign.
    if num_classes < 2:
        log.warning(
            "Only 1 class found in training data — falling back to binary:logistic. "
            "Run with full dataset (no --max-rows) for proper multi-class training."
        )
        model = xgb.XGBClassifier(
            objective="binary:logistic",
            eval_metric="logloss",
            n_estimators=100,
            max_depth=5,
            learning_rate=0.1,
            tree_method="hist",
            device="cpu",
            n_jobs=n_jobs,
            random_state=42,
            verbosity=0,
        )
        model.fit(X_train, y_train_enc, sample_weight=sample_weights)
        return model

    model = xgb.XGBClassifier(
        objective="multi:softprob",
        num_class=num_classes,
        eval_metric="mlogloss",
        n_estimators=500,
        max_depth=7,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=5,
        gamma=0.1,
        reg_alpha=0.1,
        reg_lambda=1.0,
        tree_method="hist",         # histogram-based — fast on large datasets
        device="cpu",               # change to "cuda" if GPU available
        n_jobs=n_jobs,
        random_state=42,
        early_stopping_rounds=20,
        verbosity=1,
    )

    model.fit(
        X_train,
        y_train_enc,
        sample_weight=sample_weights,
        eval_set=[(X_train, y_train_enc)],
        verbose=50,
    )
    return model


def train_isolation_forest(
    X_benign: pd.DataFrame,
    contamination: float = 0.05,
    n_jobs: int = -1,
) -> tuple[IsolationForest, float]:
    """
    Train Isolation Forest ONLY on benign traffic.

    Returns:
        iso: Fitted IsolationForest model.
        threshold: Score cutoff — scores below this flag as anomalous.
                   Derived from the 5th percentile of benign training scores.
    """
    log.info("Training Isolation Forest on %d benign samples ...", len(X_benign))

    iso = IsolationForest(
        n_estimators=200,
        max_samples="auto",
        contamination=contamination,
        max_features=1.0,
        bootstrap=False,
        n_jobs=n_jobs,
        random_state=42,
        warm_start=False,
    )
    iso.fit(X_benign)

    # Compute threshold: 5th percentile of benign scores
    # (lower score = more anomalous in sklearn's convention)
    benign_scores = iso.score_samples(X_benign)
    threshold = float(np.percentile(benign_scores, 5))
    log.info("Isolation Forest threshold (5th pct of benign scores): %.4f", threshold)

    return iso, threshold


# ── Evaluation ────────────────────────────────────────────────────────────────

def evaluate(
    model: xgb.XGBClassifier,
    X_test: pd.DataFrame,
    y_test_enc: np.ndarray,
    label_encoder: LabelEncoder,
) -> None:
    """Print classification report and macro F1 to stdout."""
    y_pred = model.predict(X_test)

    # Determine which class indices actually appear in ground-truth and predictions.
    # This avoids a sklearn crash when the loaded slice has fewer classes than
    # what the LabelEncoder knows about.
    present_labels = sorted(set(y_test_enc) | set(y_pred))
    present_names = [
        label_encoder.classes_[i]
        for i in present_labels
        if i < len(label_encoder.classes_)
    ]

    macro_f1 = f1_score(
        y_test_enc, y_pred,
        labels=present_labels,
        average="macro",
        zero_division=0,
    )

    log.info("-" * 60)
    log.info("Macro F1: %.4f", macro_f1)
    log.info("-" * 60)

    report = classification_report(
        y_test_enc,
        y_pred,
        labels=present_labels,
        target_names=present_names,
        zero_division=0,
    )
    print("\nClassification Report:\n")
    print(report)

    cm = confusion_matrix(y_test_enc, y_pred, labels=present_labels)
    print("Confusion Matrix (labels:", present_names, "):")
    print(cm)
    print()


# ── Persistence ───────────────────────────────────────────────────────────────

def save_artifacts(
    outdir: str,
    xgb_model: xgb.XGBClassifier,
    iso_model: IsolationForest,
    label_encoder: LabelEncoder,
    iso_threshold: float,
    feature_columns: list[str],
    metadata: dict = None,
) -> None:
    """Pickle all artifacts needed by inference.py into outdir."""
    Path(outdir).mkdir(parents=True, exist_ok=True)

    artifacts = {
        "xgb_model.pkl": xgb_model,
        "iso_forest.pkl": iso_model,
        "label_encoder.pkl": label_encoder,
        "feature_list.pkl": feature_columns,
        "iso_threshold.pkl": iso_threshold,
    }

    for filename, obj in artifacts.items():
        path = os.path.join(outdir, filename)
        with open(path, "wb") as f:
            pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
        log.info("Saved: %s", path)
        
    if metadata:
        meta_path = os.path.join(outdir, "model_metadata.json")
        with open(meta_path, "w") as f:
            json.dump(metadata, f, indent=2)
        log.info("Saved metadata: %s", meta_path)


# ── Main pipeline ─────────────────────────────────────────────────────────────

def train_pipeline(
    csv_paths: list[str],
    outdir: str = "models/",
    chunksize: int = 200_000,
    max_rows: int = 0,
    test_size: float = 0.2,
    contamination: float = 0.05,
) -> None:
    t0 = time.time()

    # 1. Load
    df = load_dataset(csv_paths, chunksize=chunksize, max_rows=max_rows)

    # 2. Preprocess
    X, y = preprocess(df)
    del df  # free RAM

    # 3. Encode labels
    le = LabelEncoder()
    y_enc = le.fit_transform(y)
    num_classes = len(le.classes_)
    log.info("Label classes (%d): %s", num_classes, le.classes_.tolist())

    # 4. Train / test split
    X_train, X_test, y_train_enc, y_test_enc = train_test_split(
        X, y_enc,
        test_size=test_size,
        random_state=42,
        stratify=y_enc,
    )
    log.info(
        "Split: train=%d | test=%d", len(X_train), len(X_test)
    )

    # 5. Train XGBoost
    xgb_model = train_xgboost(X_train, y_train_enc, num_classes)

    # 6. Evaluate
    evaluate(xgb_model, X_test, y_test_enc, le)

    # 7. Train Isolation Forest on BENIGN only
    benign_idx = y[y == BENIGN_LABEL].index
    # Intersect with training indices to avoid data leakage
    train_indices = X_train.index
    benign_train_idx = benign_idx.intersection(train_indices)
    X_benign = X_train.loc[benign_train_idx]

    log.info(
        "Benign training samples for IsoForest: %d / %d",
        len(X_benign), len(X_train),
    )

    if len(X_benign) == 0:
        raise RuntimeError(
            "No benign samples found in training data. "
            "Cannot train Isolation Forest. Check your dataset or label normalization."
        )

    iso_model, iso_threshold = train_isolation_forest(
        X_benign, contamination=contamination
    )

    # 8. Compute accuracy for metadata
    y_pred = xgb_model.predict(X_test)
    accuracy = np.mean(y_pred == y_test_enc)
    
    # 9. Extract Feature Importance
    importances = xgb_model.feature_importances_
    indices = np.argsort(importances)[::-1]
    
    log.info("-" * 60)
    log.info("TOP 20 MOST IMPORTANT FEATURES:")
    top_features = []
    for f in range(min(20, len(FEATURE_COLUMNS))):
        fname = FEATURE_COLUMNS[indices[f]]
        fval = importances[indices[f]]
        top_features.append({"feature": fname, "importance": float(fval)})
        log.info("%d. %s (%f)", f + 1, fname, fval)
    log.info("-" * 60)

    # Save feature importance plot
    plt.figure(figsize=(10, 8))
    plt.title("Top 20 Feature Importances (XGBoost)")
    plt.bar(range(min(20, len(FEATURE_COLUMNS))), [importances[i] for i in indices[:20]], align="center")
    plt.xticks(range(min(20, len(FEATURE_COLUMNS))), [FEATURE_COLUMNS[i] for i in indices[:20]], rotation=45, ha="right")
    plt.tight_layout()
    plt.savefig(os.path.join(outdir, "feature_importance.png"))
    plt.close()

    # 10. Save all artifacts
    metadata = {
        "model_type": "XGBClassifier",
        "training_timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "total_samples": len(X_train) + len(X_test),
        "total_features": len(FEATURE_COLUMNS),
        "total_classes": num_classes,
        "classes": le.classes_.tolist(),
        "validation_accuracy": float(accuracy),
        "top_features": top_features
    }

    save_artifacts(
        outdir=outdir,
        xgb_model=xgb_model,
        iso_model=iso_model,
        label_encoder=le,
        iso_threshold=iso_threshold,
        feature_columns=FEATURE_COLUMNS,
        metadata=metadata
    )

    elapsed = time.time() - t0
    log.info("Pipeline complete in %.1fs", elapsed)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train XGBoost + Isolation Forest NIDS pipeline on CICIoT2023."
    )
    parser.add_argument(
        "--train",
        default="data/train/train.csv",
        help="Path to training CSV (default: data/train/train.csv).",
    )
    parser.add_argument(
        "--val",
        default="data/validation/validation.csv",
        help="Path to validation CSV (default: data/validation/validation.csv).",
    )
    parser.add_argument(
        "--outdir",
        default="models/",
        help="Directory to save model artifacts.",
    )
    parser.add_argument(
        "--chunksize",
        type=int,
        default=200_000,
        help="Rows per CSV chunk (controls peak RAM usage).",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=0,
        dest="max_rows",
        help="Max total rows to load (0 = all). Use for dev/testing.",
    )
    parser.add_argument(
        "--test-size",
        type=float,
        default=0.2,
        dest="test_size",
        help="Fraction of data held out for internal evaluation (within train split).",
    )
    parser.add_argument(
        "--contamination",
        type=float,
        default=0.05,
        help="Expected anomaly fraction for Isolation Forest.",
    )
    return parser.parse_args()


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
