from fastapi import APIRouter, HTTPException
import json
import os

from backend.ml import (
    ModelManager,
    MLTrainRequest,
    MLTrainResponse,
    MLPredictRequest,
    MLPredictResponse,
    MLStatusResponse
)
from backend.utils.logger import setup_logger

router = APIRouter()
logger = setup_logger("ml_routes")

def load_metadata():
    try:
        with open("models/model_metadata.json", "r") as f:
            return json.load(f)
    except Exception:
        return {}

def load_eval_report():
    try:
        with open("models/eval/evaluation_report.json", "r") as f:
            return json.load(f)
    except Exception:
        return {}

_model_manager: ModelManager | None = None

def get_model_manager() -> ModelManager:
    global _model_manager
    if _model_manager is None:
        _model_manager = ModelManager()
    return _model_manager


@router.get("/status")
async def get_ml_status():
    manager = get_model_manager()
    meta = load_metadata()
    return {
        "models_loaded": {"hybrid_pipeline": manager.is_ready},
        "active_model": meta.get("model_type", "xgboost_iso_forest_hybrid"),
        "training_timestamp": meta.get("training_timestamp", ""),
        "total_samples": meta.get("total_samples", 0),
        "total_features": meta.get("total_features", 0),
        "total_classes": meta.get("total_classes", 0),
        "validation_accuracy": meta.get("validation_accuracy", 0.0)
    }

@router.get("/metrics")
async def get_ml_metrics():
    return load_eval_report()

@router.get("/classes")
async def get_ml_classes():
    meta = load_metadata()
    return {"classes": meta.get("classes", [])}


@router.post("/train", response_model=MLTrainResponse)
async def train_model(request: MLTrainRequest):
    # This was a mock endpoint before. We now rely on the auto-train or CLI script
    # to train on the real datasets, as the events array is too small for XGBoost.
    manager = get_model_manager()
    if not manager.is_ready:
        # Trigger background auto train if forced
        import threading
        threading.Thread(target=manager.auto_train_if_needed).start()
        
    return MLTrainResponse(
        status="training_started",
        model="xgboost_iso_forest_hybrid",
        samples_trained=0
    )


@router.post("/predict", response_model=MLPredictResponse)
async def predict(request: MLPredictRequest):
    try:
        manager = get_model_manager()
        node_data = {"id": request.node_id, "features": request.features}
        enriched = manager.score_node(node_data)
        
        return MLPredictResponse(
            node_id=enriched["id"],
            anomaly_score=enriched.get("anomaly_score", 0.0),
            status=enriched.get("status", "benign"),
            ml_flag=enriched.get("ml_flag", False)
        )
    except Exception as e:
        logger.error(f"Prediction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

