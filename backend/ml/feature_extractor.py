def extract_features(event: dict) -> list[float]:
    """
    Extracts deterministic numeric features from a telemetry event dictionary.
    Ensures a consistent array shape for the ML model.
    """
    return [
        float(event.get("failed_login_count", 0.0)),
        float(event.get("connection_count", 1.0)),
        float(event.get("unusual_port_usage", 0.0)),
        float(event.get("alert_frequency", 0.0)),
        float(event.get("packet_spike", 0.0)),
        float(event.get("privilege_escalation_count", 0.0)),
        float(event.get("process_anomaly_count", 0.0)),
    ]
