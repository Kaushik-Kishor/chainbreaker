"""
inference.py — Real-time inference module for the ChainBreaker NIDS.

Designed for direct drop-in use inside the Kafka consumer pipeline.

Usage:
    from backend.ml.inference import NIDSPredictor

    predictor = NIDSPredictor()  # loads models once at startup
    result = predictor.predict_flow(flow_dict)
    # result → {"attack_type": str, "confidence": float,
    #            "anomaly_score": float, "final_label": str}
"""

from __future__ import annotations

import logging
import os
import pickle
from functools import lru_cache
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import LabelEncoder
import xgboost as xgb

from backend.ml.features import BENIGN_LABEL, FEATURE_COLUMNS, normalize_label

log = logging.getLogger(__name__)

# Default artifact directory — can be overridden via env var
_DEFAULT_MODEL_DIR = os.environ.get("MODEL_DIR", "models/")

# Final-label thresholds
_CONFIDENCE_THRESHOLD = float(os.environ.get("XGB_CONFIDENCE_THRESHOLD", "0.5"))


# ── Probability calibration ───────────────────────────────────────────────────
# XGBoost on well-separated datasets like CICIoT2023 produces max-probabilities
# in a very narrow band (0.995 – 0.99999).  A naive max(proba)*100 always rounds
# to 100%.  We use a log-space rescaling that maps the *meaningful* micro-
# differences within that band into a visible 60-100% confidence range.
#
#   -log10(1 - p)  maps:
#     p=0.99   → 2.0
#     p=0.999  → 3.0
#     p=0.9999 → 4.0
#
# We linearly map [2.0, 5.0] → [60%, 100%], clamped.
# This is monotonic: higher raw probability ↔ higher calibrated confidence.

def _calibrate_confidence(raw_prob: float) -> float:
    """Convert a raw max-probability into a calibrated 0-100 confidence %."""
    clamped = float(np.clip(raw_prob, 0.0, 1.0))
    if clamped <= 0.0:
        return 0.0
    if clamped >= 1.0 - 1e-15:
        return 100.0
    neg_log = -np.log10(1.0 - clamped)
    # Map [2.0, 5.0] → [60, 100];  below 2.0 clamps to 60, above 5.0 to 100
    calibrated = 60.0 + (neg_log - 2.0) * (40.0 / 3.0)
    return round(float(np.clip(calibrated, 0.0, 100.0)), 1)


# ── Artifact loader ───────────────────────────────────────────────────────────

def _load_pickle(path: str) -> Any:
    with open(path, "rb") as f:
        return pickle.load(f)


# ── Predictor class ───────────────────────────────────────────────────────────

class NIDSPredictor:
    """
    Thread-safe inference wrapper.

    Loads all artifacts once on construction and exposes a single
    `predict_flow` method called once per network flow.

    Attributes:
        xgb_model       : Trained XGBClassifier.
        iso_model        : Trained IsolationForest.
        label_encoder    : LabelEncoder mapping int indices ↔ class strings.
        feature_columns  : Ordered list of feature column names.
        iso_threshold    : Score below this → SUSPICIOUS.
    """

    def __init__(self, model_dir: str | None = None) -> None:
        if model_dir is None:
            # Dynamic directory scanning for latest versioned model
            base_dir = _DEFAULT_MODEL_DIR
            latest_version_dir = None
            if os.path.exists(base_dir):
                versions = [d for d in os.listdir(base_dir) if d.startswith("v_") and os.path.isdir(os.path.join(base_dir, d))]
                if versions:
                    latest_version_dir = os.path.join(base_dir, sorted(versions)[-1])
            model_dir = latest_version_dir or base_dir

        log.info("[NIDSPredictor] Loading artifacts from: %s", model_dir)

        self.model_version = os.path.basename(model_dir.rstrip('/\\')) if "v_" in model_dir else "unknown"

        self.xgb_model: xgb.XGBClassifier = _load_pickle(
            os.path.join(model_dir, "xgb_model.pkl")
        )
        self.iso_model: IsolationForest = _load_pickle(
            os.path.join(model_dir, "iso_forest.pkl")
        )
        self.label_encoder: LabelEncoder = _load_pickle(
            os.path.join(model_dir, "label_encoder.pkl")
        )
        self.feature_columns: list[str] = _load_pickle(
            os.path.join(model_dir, "feature_list.pkl")
        )
        self.iso_threshold: float = _load_pickle(
            os.path.join(model_dir, "iso_threshold.pkl")
        )
        self._benign_class_idx: int = int(
            np.where(self.label_encoder.classes_ == BENIGN_LABEL)[0][0]
        )

        log.info(
            "[NIDSPredictor] Ready. Classes=%d | iso_threshold=%.4f",
            len(self.label_encoder.classes_),
            self.iso_threshold,
        )

    # ── Feature extraction ────────────────────────────────────────────────────

    def _extract_features(self, flow: dict[str, Any]) -> pd.DataFrame:
        """
        Extract and validate features from a raw flow dict.

        Handles:
        - Missing columns → filled with 0.0
        - Non-numeric values → coerced to 0.0
        - Inf / NaN → 0.0

        Returns a single-row DataFrame with columns = self.feature_columns.
        """
        row: dict[str, float] = {}
        for col in self.feature_columns:
            raw = flow.get(col, flow.get("props", {}).get(col, 0.0))
            try:
                val = float(raw)
                if val != val or val == float("inf") or val == float("-inf"):
                    val = 0.0
            except (TypeError, ValueError):
                val = 0.0
            row[col] = val

        return pd.DataFrame([row], columns=self.feature_columns, dtype=np.float32)

    # ── Core prediction ───────────────────────────────────────────────────────

    def predict_flow(self, flow_dict: dict[str, Any]) -> dict[str, Any]:
        """
        Predict attack type and anomaly score for a single network flow.

        Args:
            flow_dict: Raw flow dict as produced by cicflow_parser.py.
                       Keys may include top-level field names OR a nested
                       "props" dict containing CICFlowMeter column names.

        Returns:
            {
                "attack_type"   : str   — predicted subLabelCat (e.g. "ddos")
                "confidence"    : float — XGBoost probability [0, 1]
                "anomaly_score" : float — IsoForest score (lower = more anomalous)
                "final_label"   : str   — "BENIGN" | "ATTACK" | "SUSPICIOUS"
                "model_version" : str   - Version of the model used
                "prediction_timestamp": str - ISO formatted timestamp
                "inference_latency": float - Latency in seconds
            }
        """
        import time
        from datetime import datetime
        start_time = time.perf_counter()

        # 1. Extract features
        X = self._extract_features(flow_dict)

        # 2. XGBoost inference
        proba = self.xgb_model.predict_proba(X)[0]           # shape: (num_classes,)
        predicted_idx = int(np.argmax(proba))
        raw_confidence = float(np.max(proba))
        attack_type: str = self.label_encoder.classes_[predicted_idx]

        # 3. Isolation Forest anomaly score
        # score_samples returns higher = more normal, lower = more anomalous
        raw_score = float(self.iso_model.score_samples(X)[0])
        # Normalize to [0, 1] where 1 = maximally anomalous (for easier consumption)
        # We invert and clip so downstream consumers see a "risk score"
        anomaly_score = float(np.clip(-raw_score, 0.0, 1.0))
        is_anomaly = raw_score < self.iso_threshold

        confidence_pct = _calibrate_confidence(raw_confidence)

        log.info(
            "Prediction=%s confidence=%.1f%% raw_prob=%.6f",
            attack_type,
            confidence_pct,
            raw_confidence,
        )

        # 4. Decision logic — uses raw probability, NOT calibrated display value
        #    Priority: XGB attack prediction > anomaly flag > benign
        if attack_type != BENIGN_LABEL and raw_confidence >= _CONFIDENCE_THRESHOLD:
            final_label = "ATTACK"
        elif is_anomaly:
            final_label = "SUSPICIOUS"
        else:
            final_label = "BENIGN"
            
        latency = time.perf_counter() - start_time

        return {
            "attack_type": attack_type,
            "confidence": confidence_pct,
            "anomaly_score": round(anomaly_score, 6),
            "final_label": final_label,
            "model_version": self.model_version,
            "prediction_timestamp": datetime.utcnow().isoformat() + "Z",
            "inference_latency": latency,
        }

    def predict_batch(
        self, flow_dicts: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Vectorized batch inference — significantly faster than calling
        predict_flow in a loop for large batches.

        Returns a list of result dicts in the same order as the input.
        """
        if not flow_dicts:
            return []

        import time
        from datetime import datetime
        start_time = time.perf_counter()

        # Build feature matrix in one shot
        rows = [self._extract_features(f).iloc[0].to_dict() for f in flow_dicts]
        X = pd.DataFrame(rows, columns=self.feature_columns, dtype=np.float32)

        # XGBoost batch
        probas = self.xgb_model.predict_proba(X)               # (N, num_classes)
        predicted_idxs = np.argmax(probas, axis=1)
        confidences = np.max(probas, axis=1)
        attack_types = self.label_encoder.classes_[predicted_idxs]

        # IsoForest batch
        raw_scores = self.iso_model.score_samples(X)            # (N,)
        anomaly_scores = np.clip(-raw_scores, 0.0, 1.0)
        is_anomalies = raw_scores < self.iso_threshold
        
        latency = time.perf_counter() - start_time
        avg_latency = latency / len(flow_dicts) if flow_dicts else 0.0
        prediction_timestamp = datetime.utcnow().isoformat() + "Z"

        results = []
        for i in range(len(flow_dicts)):
            att = attack_types[i]
            raw_conf = float(confidences[i])
            anom = float(anomaly_scores[i])
            is_anom = bool(is_anomalies[i])

            conf_pct = _calibrate_confidence(raw_conf)

            if att != BENIGN_LABEL and raw_conf >= _CONFIDENCE_THRESHOLD:
                final = "ATTACK"
            elif is_anom:
                final = "SUSPICIOUS"
            else:
                final = "BENIGN"

            results.append({
                "attack_type": att,
                "confidence": conf_pct,
                "anomaly_score": round(anom, 6),
                "final_label": final,
                "model_version": self.model_version,
                "prediction_timestamp": prediction_timestamp,
                "inference_latency": avg_latency,
            })

        return results


# ── Module-level singleton (lazy) ─────────────────────────────────────────────
# The Kafka consumer can call predict_flow() via the module-level function
# without managing the predictor object lifecycle.

_predictor: NIDSPredictor | None = None


def _get_predictor() -> NIDSPredictor:
    global _predictor
    if _predictor is None:
        _predictor = NIDSPredictor()
    return _predictor


def predict_flow(flow_dict: dict[str, Any]) -> dict[str, Any]:
    """
    Module-level convenience wrapper.

    Drop-in for Kafka consumer integration:

        from backend.ml.inference import predict_flow

        result = predict_flow(parsed_flow)
    """
    return _get_predictor().predict_flow(flow_dict)
