import argparse
import logging
import json
import os
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    precision_recall_fscore_support,
    accuracy_score
)
from sklearn.preprocessing import LabelEncoder
import xgboost as xgb

from backend.ml.features import FEATURE_COLUMNS, normalize_label, TARGET_COLUMN

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("evaluate")

def load_artifacts(model_dir: str):
    """Load the XGBoost model, label encoder, and feature list."""
    try:
        with open(os.path.join(model_dir, "xgb_model.pkl"), "rb") as f:
            xgb_model = pickle.load(f)
        with open(os.path.join(model_dir, "label_encoder.pkl"), "rb") as f:
            le = pickle.load(f)
        with open(os.path.join(model_dir, "feature_list.pkl"), "rb") as f:
            features = pickle.load(f)
        return xgb_model, le, features
    except Exception as e:
        log.error("Failed to load artifacts from %s: %s", model_dir, e)
        sys.exit(1)

def evaluate_pipeline(data_path: str, model_dir: str, output_dir: str):
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    log.info("Loading evaluation dataset from %s", data_path)
    if not os.path.exists(data_path):
        log.error("Dataset not found: %s", data_path)
        return

    df = pd.read_csv(data_path)
    
    xgb_model, le, expected_features = load_artifacts(model_dir)

    # ── Preprocess ────────────────────────────────────────────────────────
    y = df[TARGET_COLUMN].apply(normalize_label)
    
    # Select features
    for col in expected_features:
        if col not in df.columns:
            df[col] = 0.0
            
    X = df[expected_features].copy()
    
    for col in X.columns:
        X[col] = pd.to_numeric(X[col], errors="coerce")
        
    X.replace([np.inf, -np.inf], np.nan, inplace=True)
    X.fillna(0.0, inplace=True)
    X = X.astype(np.float32)

    # Known labels
    known_mask = y.isin(le.classes_)
    if not known_mask.all():
        log.warning("Dropping %d rows with unknown labels.", (~known_mask).sum())
        X = X[known_mask]
        y = y[known_mask]

    y_enc = le.transform(y)

    log.info("Running inference on %d rows...", len(X))
    y_pred = xgb_model.predict(X)
    
    # Also get probabilities to analyze confidence
    y_prob = xgb_model.predict_proba(X)
    y_prob_max = np.max(y_prob, axis=1)

    # ── Metrics ───────────────────────────────────────────────────────────
    accuracy = accuracy_score(y_enc, y_pred)
    log.info("Overall Accuracy: %.4f", accuracy)

    # Support and per-class metrics
    present_labels = np.unique(np.concatenate([y_enc, y_pred]))
    present_names = le.inverse_transform(present_labels)

    precision, recall, f1, support = precision_recall_fscore_support(
        y_enc, y_pred, labels=present_labels, zero_division=0
    )

    per_class_metrics = {}
    for i, name in enumerate(present_names):
        per_class_metrics[name] = {
            "precision": float(precision[i]),
            "recall": float(recall[i]),
            "f1_score": float(f1[i]),
            "support": int(support[i])
        }

    macro_f1 = np.mean(f1)
    weighted_f1 = np.average(f1, weights=support)
    
    # ── ROC-AUC ───────────────────────────────────────────────────────────
    try:
        from sklearn.metrics import roc_auc_score
        roc_auc = float(roc_auc_score(y_enc, y_prob, multi_class="ovr", average="macro", labels=present_labels))
        log.info("ROC-AUC (Macro, OVR): %.4f", roc_auc)
    except Exception as e:
        log.warning("Could not calculate ROC-AUC: %s", e)
        roc_auc = None

    # ── Top-K Confused Classes ────────────────────────────────────────────
    cm = confusion_matrix(y_enc, y_pred, labels=present_labels)
    
    confused_pairs = []
    for i in range(len(present_labels)):
        for j in range(len(present_labels)):
            if i != j and cm[i, j] > 0:
                true_label = present_names[i]
                pred_label = present_names[j]
                count = int(cm[i, j])
                confused_pairs.append({
                    "true_label": true_label,
                    "predicted_label": pred_label,
                    "count": count
                })
                
    confused_pairs.sort(key=lambda x: x["count"], reverse=True)
    top_k_confused = confused_pairs[:10]

    log.info("Top 5 Confused Classes:")
    for pair in top_k_confused[:5]:
        log.info("  %s -> %s : %d", pair["true_label"], pair["predicted_label"], pair["count"])

    # ── Confidence Distribution ───────────────────────────────────────────
    correct_mask = (y_pred == y_enc)
    avg_confidence_correct = float(np.mean(y_prob_max[correct_mask])) if np.sum(correct_mask) > 0 else 0.0
    avg_confidence_incorrect = float(np.mean(y_prob_max[~correct_mask])) if np.sum(~correct_mask) > 0 else 0.0

    # ── Save Report ───────────────────────────────────────────────────────
    report = {
        "overall": {
            "accuracy": float(accuracy),
            "macro_f1": float(macro_f1),
            "weighted_f1": float(weighted_f1),
            "roc_auc": roc_auc,
            "avg_confidence_correct": avg_confidence_correct,
            "avg_confidence_incorrect": avg_confidence_incorrect,
        },
        "per_class": per_class_metrics,
        "top_confused_pairs": top_k_confused
    }

    report_path = os.path.join(output_dir, "evaluation_report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    log.info("Saved evaluation report to %s", report_path)

    # ── Save Confusion Matrix Image ───────────────────────────────────────
    plt.figure(figsize=(16, 14))
    sns.heatmap(cm, xticklabels=present_names, yticklabels=present_names, cmap="Blues", annot=False)
    plt.title("Confusion Matrix")
    plt.xlabel("Predicted")
    plt.ylabel("True")
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "confusion_matrix.png"), dpi=150)
    plt.close()
    
    log.info("Saved confusion matrix image to %s", os.path.join(output_dir, "confusion_matrix.png"))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate the trained NIDS ML model.")
    parser.add_argument("--data", default="data/validation/validation.csv", help="Path to evaluation dataset")
    parser.add_argument("--model-dir", default="models/", help="Path to model artifacts")
    parser.add_argument("--outdir", default="models/eval/", help="Output directory for reports")
    args = parser.parse_args()

    model_dir = args.model_dir
    if model_dir == "models/":
        # Dynamic directory scanning for latest versioned model
        if os.path.exists(model_dir):
            versions = [d for d in os.listdir(model_dir) if d.startswith("v_") and os.path.isdir(os.path.join(model_dir, d))]
            if versions:
                model_dir = os.path.join(model_dir, sorted(versions)[-1])
                log.info("Dynamically selected latest model directory: %s", model_dir)
                
    # Update outdir to match model version
    outdir = args.outdir
    if args.outdir == "models/eval/" and "v_" in model_dir:
        outdir = os.path.join(model_dir, "eval")

    evaluate_pipeline(args.data, model_dir, outdir)
