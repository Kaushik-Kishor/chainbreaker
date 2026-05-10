"""
flow_writer.py — Batched Neo4j flow ingestion.
No structlog. No over-engineering.
"""

import hashlib
from datetime import datetime
from typing import Any

from backend.graph.neo4j_client import neo4j_client


# ── Cypher ────────────────────────────────────────────────────────────────────

_INGEST_CYPHER = """
UNWIND $batch AS row

MERGE (src:Host {ip: row.src_ip})
  ON CREATE SET src.first_seen = row.ts, src.last_seen = row.ts
  ON MATCH  SET src.last_seen  = row.ts

MERGE (dst:Host {ip: row.dst_ip})
  ON CREATE SET dst.first_seen = row.ts, dst.last_seen = row.ts
  ON MATCH  SET dst.last_seen  = row.ts

MERGE (flow:Flow {flow_id: row.flow_id})
SET flow += row.props

MERGE (src)-[:INITIATED]->(flow)
MERGE (flow)-[:TARGETS]->(dst)

MERGE (src)-[comm:COMMUNICATES_WITH]->(dst)
  ON CREATE SET comm.first_seen = row.ts, comm.last_seen = row.ts, comm.flow_count = 1
  ON MATCH  SET comm.last_seen  = row.ts, comm.flow_count = comm.flow_count + 1

MERGE (proto:Protocol {name: row.protocol})
MERGE (flow)-[:USES_PROTOCOL]->(proto)

FOREACH (_ IN CASE WHEN row.label <> 'BenignTraffic' THEN [1] ELSE [] END |
  MERGE (atk:Attack {label: row.label, subLabel: row.subLabel})
  MERGE (flow)-[:HAS_ATTACK_TYPE]->(atk)
)
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _f(v: Any, default: float = 0.0) -> float:
    """Safe float — returns default for None / NaN / Inf."""
    try:
        r = float(v)
        return default if (r != r or r == float("inf") or r == float("-inf")) else r
    except (TypeError, ValueError):
        return default


def _i(v: Any, default: int = 0) -> int:
    """Safe int."""
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _flow_id(flow: dict) -> str:
    """Deterministic 16-char hex id from flow identity fields."""
    raw = "|".join([
        str(flow.get("timestamp", "")),
        str(flow.get("src_ip", "")),
        str(flow.get("src_port", "")),
        str(flow.get("dst_ip", "")),
        str(flow.get("dst_port", "")),
        str(flow.get("protocol", "")),
    ])
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _build_row(flow: dict) -> dict:
    """Map a parsed flow dict to a Neo4j UNWIND row parameter."""
    ts = flow.get("timestamp", datetime.utcnow().isoformat())
    label = str(flow.get("label", "BenignTraffic")).strip()
    sublabel = str(flow.get("sublabel", flow.get("subLabel", ""))).strip()
    protocol = str(flow.get("protocol", "TCP")).strip() or "TCP"
    raw_props = flow.get("props")
    if not isinstance(raw_props, dict):
        raw_props = {}

    props = {
        # identity
        "flow_id":       _flow_id(flow),
        "ts":            ts,
        "src_ip":        str(flow.get("src_ip", "")).strip(),
        "dst_ip":        str(flow.get("dst_ip", "")).strip(),
        "src_port":      _i(raw_props.get("Source Port", flow.get("src_port"))),
        "dst_port":      _i(raw_props.get("Destination Port", flow.get("dst_port"))),
        "protocol":      protocol,
        # volume
        "total_size":    _f(raw_props.get("Tot size", flow.get("total_size"))),
        "total_bytes":   _f(raw_props.get("Tot sum", flow.get("total_bytes"))),
        "rate":          _f(raw_props.get("Rate", flow.get("rate"))),
        "srate":         _f(raw_props.get("Srate", flow.get("srate"))),
        "drate":         _f(raw_props.get("Drate", flow.get("drate"))),
        # duration
        "flow_duration": _f(raw_props.get("flow_duration", raw_props.get("Duration", flow.get("flow_duration")))),
        # TCP flags
        "syn_flag_count": _i(raw_props.get("syn_flag_number", flow.get("syn_flag_count"))),
        "ack_flag_count": _i(raw_props.get("ack_flag_number", flow.get("ack_flag_count"))),
        "fin_flag_count": _i(raw_props.get("fin_flag_number", flow.get("fin_flag_count"))),
        "rst_flag_count": _i(raw_props.get("rst_flag_number", flow.get("rst_flag_count"))),
        "psh_flag_count": _i(raw_props.get("psh_flag_number", flow.get("psh_flag_count"))),
        "urg_flag_count": _i(raw_props.get("urg_flag_number", flow.get("urg_flag_count"))),
        "ece_flag_count": _i(raw_props.get("ece_flag_number", flow.get("ece_flag_count"))),
        "cwr_flag_count": _i(raw_props.get("cwr_flag_number", flow.get("cwr_flag_count"))),
        # stats
        "header_length": _f(raw_props.get("Header_Length", flow.get("header_length"))),
        "iat":           _f(raw_props.get("IAT", flow.get("iat"))),
        "magnitude":     _f(raw_props.get("Magnitue", raw_props.get("Magnitude", flow.get("magnitude")))),
        "radius":        _f(raw_props.get("Radius", flow.get("radius"))),
        "covariance":    _f(raw_props.get("Covariance", flow.get("covariance"))),
        "variance":      _f(raw_props.get("Variance", flow.get("variance"))),
        "weight":        _f(raw_props.get("Weight", flow.get("weight"))),
        # labels
        "label":         label,
        "sublabel":      sublabel,
        "sublabel_cat":  str(raw_props.get("subLabelCat", flow.get("sublabel_cat", flow.get("subLabelCat", "")))).strip(),
        # ML placeholders and metadata
        "predicted_label":      flow.get("predicted_label"),
        "confidence_score":     flow.get("confidence_score"),
        "anomaly_score":        flow.get("anomaly_score"),
        "final_label":          flow.get("final_label"),
        "model_version":        flow.get("model_version"),
        "prediction_timestamp": flow.get("prediction_timestamp"),
        "inference_latency":    flow.get("inference_latency"),
    }

    return {
        "flow_id":  props["flow_id"],
        "ts":       ts,
        "src_ip":   props["src_ip"],
        "dst_ip":   props["dst_ip"],
        "protocol": protocol,
        "label":    label,
        "subLabel": sublabel,
        "props":    props,
    }


# ── Public API ────────────────────────────────────────────────────────────────

async def ingest_flow_batch(flows: list[dict]) -> int:
    """
    Ingest a batch of parsed flows into Neo4j.

    Uses a single UNWIND Cypher query for the entire batch.
    Returns the number of flows successfully ingested.
    """
    if not flows:
        return 0

    valid = []
    for flow in flows:
        if not flow["src_ip"] or not flow["dst_ip"]:
            continue
        valid.append(flow)

    if not valid:
        print(f"[flow_writer] WARNING: 0/{len(flows)} flows had valid IPs — skipping batch")
        return 0

    batch = [_build_row(f) for f in valid]

    try:
        await neo4j_client.execute(_INGEST_CYPHER, {"batch": batch})
        attacks = sum(1 for r in batch if r["label"] != "BenignTraffic")
        print(f"[flow_writer] Ingested {len(batch)} flows ({attacks} attacks, {len(batch) - attacks} benign)")
        return len(batch)
    except Exception as exc:
        print(f"[flow_writer] ERROR ingesting batch of {len(batch)}: {exc}")
        raise
