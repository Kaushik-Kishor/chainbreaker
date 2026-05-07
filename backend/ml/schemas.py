from pydantic import BaseModel, Field

class MLPredictRequest(BaseModel):
    node_id: str
    features: dict[str, float | int] = Field(default_factory=dict)

class MLPredictResponse(BaseModel):
    node_id: str
    anomaly_score: float
    status: str
    ml_flag: bool

class MLTrainRequest(BaseModel):
    events: list[dict[str, float | int]]

class MLTrainResponse(BaseModel):
    status: str
    model: str
    samples_trained: int

class MLStatusResponse(BaseModel):
    models_loaded: dict[str, bool]
    active_model: str
