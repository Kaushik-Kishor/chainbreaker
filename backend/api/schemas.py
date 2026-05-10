from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class HostResponse(BaseModel):
    ip: str
    hostname: str | None = None
    role: str
    compromise_status: str
    first_seen: str | None = None
    last_seen: str | None = None
    connected_peers: int = 0


class AttackEventResponse(BaseModel):
    event_id: str
    stage: str
    timestamp: str
    confidence: float
    risk_indicator: str  # Renamed from attack_label to mask raw labels
    source_ip: str
    dest_ip: str
    ml_model: str


class KillChainStageResponse(BaseModel):
    stage_id: str
    stage: str
    host_ip: str
    status: str
    first_detected: str | None = None
    last_updated: str | None = None
    containment_attempts: int = 0
    dwell_time_seconds: float = 0.0


class AlertResponse(BaseModel):
    alert_id: str
    title: str
    severity: str
    status: str
    stage: str
    created_at: str
    updated_at: str
    affected_hosts: list[str] = Field(default_factory=list)
    description: str | None = None


class ForensicTimelineItem(BaseModel):
    event_id: str
    stage: str
    label: str
    confidence: float
    timestamp: str
    source_ip: str
    dest_ip: str
    kill_chain_status: str | None = None
    agent_action: str | None = None
    action_success: bool | None = None
    alert_id: str | None = None


class BlastRadiusResponse(BaseModel):
    total_compromised: int
    total_events: int
    total_alerts: int
    high_value_impact: int
    exposed_peers: int
    severity_score: int
    severity_level: str
    compromised_hosts: list[dict[str, Any]]


class ForensicReportResponse(BaseModel):
    report_id: str
    generated_at: str
    blast_radius: dict[str, Any]
    kill_chain_summary: dict[str, Any]
    affected_assets: list[dict[str, Any]]
    attack_path: list[dict[str, Any]]
    recommendations: list[str]


class MLStatusResponse(BaseModel):
    models_loaded: dict[str, bool]
    active_model: str


class AgentActionResponse(BaseModel):
    action_id: str
    action_type: str
    stage: str
    host_ip: str
    timestamp: str
    success: bool
    reason: str
