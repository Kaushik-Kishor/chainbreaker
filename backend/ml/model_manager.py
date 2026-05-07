"""
model_manager.py — Model lifecycle manager for the ChainBreaker NIDS.

- Auto-trains on CICIoT2023 train.csv if no model artifacts exist.
- Validates that trained models are multiclass (expects ~34 classes).
- Exposes score_node() for real-time WebSocket telemetry scoring.
"""

import os
import threading

from backend.ml.inference import _get_predictor, NIDSPredictor
from backend.ml.train import train_pipeline
from backend.utils.logger import setup_logger

logger = setup_logger("model_manager")

_BASE = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
MODEL_DIR = os.path.join(_BASE, "models")
TRAIN_CSV = os.path.join(_BASE, "data", "train", "train.csv")
VAL_CSV   = os.path.join(_BASE, "data", "validation", "validation.csv")

# Minimum acceptable class count — reject single-class models
MIN_CLASSES = 2


class ModelManager:
    def __init__(self):
        self.is_ready = False
        self._lock = threading.Lock()

    def auto_train_if_needed(self):
        """
        Check for existing model artifacts. If they exist AND are multiclass,
        load them. If missing or single-class, retrain from scratch.
        """
        with self._lock:
            xgb_path = os.path.join(MODEL_DIR, "xgb_model.pkl")

            if os.path.exists(xgb_path):
                logger.info("Model artifacts found at %s — validating...", MODEL_DIR)
                try:
                    predictor = _get_predictor()
                    n_classes = len(predictor.label_encoder.classes_)
                    class_names = list(predictor.label_encoder.classes_)

                    if n_classes < MIN_CLASSES:
                        logger.warning(
                            "MODEL REJECTED: only %d class(es) found: %s. "
                            "Deleting stale artifacts and retraining...",
                            n_classes, class_names,
                        )
                        self._delete_artifacts()
                        # Fall through to training
                    else:
                        logger.info(
                            "MODEL VALIDATED: %d classes loaded: %s",
                            n_classes, class_names,
                        )
                        logger.info(
                            "Feature count: %d | Iso threshold: %.4f",
                            len(predictor.feature_columns),
                            predictor.iso_threshold,
                        )
                        self.is_ready = True
                        return
                except Exception as e:
                    logger.error("Failed to load model artifacts: %s. Retraining...", e)
                    self._delete_artifacts()

            # ── Train from scratch ────────────────────────────────────────
            logger.warning(
                "Auto-training multiclass model on CICIoT2023: %s", TRAIN_CSV
            )
            try:
                train_pipeline(
                    csv_paths=[TRAIN_CSV],
                    outdir=MODEL_DIR,
                    chunksize=100_000,
                    max_rows=200_000,
                )
                # Validate the freshly trained model
                import importlib
                import backend.ml.inference as inf_mod
                importlib.reload(inf_mod)
                inf_mod._predictor = None
                predictor = inf_mod._get_predictor()

                n_classes = len(predictor.label_encoder.classes_)
                logger.info(
                    "TRAINING COMPLETE: %d classes: %s",
                    n_classes, list(predictor.label_encoder.classes_),
                )
                if n_classes < MIN_CLASSES:
                    logger.error(
                        "CRITICAL: Training produced only %d class(es). "
                        "Check TARGET_COLUMN and dataset labels!", n_classes
                    )
                self.is_ready = True

            except Exception as e:
                logger.error("Auto-training failed: %s", e, exc_info=True)

    def _delete_artifacts(self):
        """Remove stale model pkl files to force retraining."""
        import glob
        for f in glob.glob(os.path.join(MODEL_DIR, "*.pkl")):
            try:
                os.remove(f)
                logger.info("Deleted stale artifact: %s", f)
            except OSError:
                pass

    def score_node(self, node_data: dict) -> dict:
        """
        Score a node through the hybrid XGB + IsolationForest predictor.
        Returns enriched dict with status, attack_type, confidence, anomaly_score.
        """
        if not self.is_ready:
            enriched = dict(node_data)
            enriched.setdefault("status", "benign")
            enriched.setdefault("attack_type", "BenignTraffic")
            enriched.setdefault("confidence", 0.0)
            enriched.setdefault("anomaly_score", 0.0)
            return enriched

        try:
            predictor = _get_predictor()
            features  = node_data.get("features", {})
            result    = predictor.predict_flow(features)

            enriched = dict(node_data)
            enriched["anomaly_score"] = round(result.get("anomaly_score", 0.0) * 100, 2)
            enriched["confidence"]    = result.get("confidence", 0.0)
            enriched["attack_type"]   = result.get("attack_type", "BenignTraffic")

            fl = result.get("final_label", "BENIGN")
            enriched["status"] = (
                "attack"     if fl == "ATTACK"     else
                "suspicious" if fl == "SUSPICIOUS" else
                "benign"
            )
            return enriched

        except Exception as e:
            logger.error("score_node failed for '%s': %s", node_data.get("id", "?"), e)
            enriched = dict(node_data)
            enriched.setdefault("status", "benign")
            enriched.setdefault("attack_type", "BenignTraffic")
            enriched.setdefault("confidence", 0.0)
            enriched.setdefault("anomaly_score", 0.0)
            return enriched
