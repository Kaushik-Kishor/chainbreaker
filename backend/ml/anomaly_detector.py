import os
import pickle
from sklearn.ensemble import IsolationForest
from backend.utils.logger import setup_logger

logger = setup_logger("anomaly_detector")

class AnomalyDetector:
    def __init__(self, contamination: float = 0.05):
        self.model = IsolationForest(
            n_estimators=100, 
            contamination=contamination, 
            random_state=42, 
            n_jobs=-1
        )
        self.is_trained = False

    def train(self, X: list[list[float]]):
        if not X:
            logger.warning("No data provided for training.")
            return
        
        try:
            self.model.fit(X)
            self.is_trained = True
            logger.info(f"IsolationForest trained on {len(X)} samples.")
        except Exception as e:
            logger.error(f"Failed to train IsolationForest: {e}")
            self.is_trained = False

    def predict_score(self, x: list[float]) -> float:
        """
        Returns anomaly score from 0.0 (normal) to 1.0 (highly anomalous).
        IsolationForest returns scores where lower is more anomalous (usually between -0.5 and 0.5).
        We invert and normalize it roughly to [0, 1].
        """
        if not self.is_trained:
            # Fallback if not trained
            return sum(x) / (sum(x) + 10.0)
        
        try:
            # score_samples returns opposite of anomaly score (lower is more abnormal)
            raw_score = self.model.score_samples([x])[0]
            # Map raw score (approx -1.0 to 0.5) to a 0.0 -> 1.0 range where 1.0 is bad
            normalized_score = max(0.0, min(1.0, -raw_score))
            return float(normalized_score)
        except Exception as e:
            logger.error(f"Prediction failed: {e}")
            return 0.0

    def save(self, filepath: str):
        try:
            with open(filepath, 'wb') as f:
                pickle.dump(self, f)
            logger.info(f"Model saved to {filepath}")
        except Exception as e:
            logger.error(f"Failed to save model: {e}")

    @staticmethod
    def load(filepath: str) -> 'AnomalyDetector':
        if not os.path.exists(filepath):
            logger.info(f"Model file {filepath} not found. Creating new model.")
            return AnomalyDetector()
        
        try:
            with open(filepath, 'rb') as f:
                model = pickle.load(f)
                logger.info(f"Model loaded from {filepath}")
                return model
        except Exception as e:
            logger.error(f"Failed to load model from {filepath}: {e}. Creating new model.")
            return AnomalyDetector()
