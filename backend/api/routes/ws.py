"""
ws.py — WebSocket endpoint + live telemetry replay from CICIoT2023 test.csv

CICIoT2023 has no IP columns. IPs are synthesized deterministically from each
row's label + flow metadata to build a rich, persistent network topology.

The graph builds up a realistic SOC attack map with:
 - Persistent attacker pools per attack family
 - Persistent victim/server/IoT pools
 - Internal gateway and router nodes
 - DDoS fan-out patterns
 - Lateral movement clusters
"""

import asyncio
import hashlib
import ipaddress
import os
import random

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.graph.neo4j_client import neo4j_client
from backend.utils.logger import setup_logger
from backend.utils.csv_loader import load_dataset_with_fallback

router = APIRouter()
logger = setup_logger("ws_routes")

# ── Dataset path ──────────────────────────────────────────────────────────────
_BASE    = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TEST_CSV = os.path.join(_BASE, "data", "test", "test.csv")

# ── Replay config ─────────────────────────────────────────────────────────────
REPLAY_INTERVAL = float(os.environ.get("TELEMETRY_REPLAY_INTERVAL", "0.3"))

# ═══════════════════════════════════════════════════════════════════════════════
#  TOPOLOGY ENGINE — Deterministic IP Pools
# ═══════════════════════════════════════════════════════════════════════════════

# External attackers — spread across multiple C2 subnets
_EXT_ATTACKERS = (
    [f"203.0.113.{i}" for i in range(1, 40)]
    + [f"198.51.100.{i}" for i in range(1, 30)]
    + [f"45.33.32.{i}" for i in range(1, 20)]
)

# Internal victim servers
_SERVERS = [
    f"192.168.1.{i}" for i in range(10, 35)
] + [
    f"10.0.1.{i}" for i in range(10, 25)
]

# IoT devices
_IOT = [f"192.168.10.{i}" for i in range(100, 140)]

# Workstations / clients
_WORKSTATIONS = [f"192.168.1.{i}" for i in range(50, 90)]

# Infrastructure: gateways, DNS, firewalls
_INFRA = [
    "192.168.1.1", "192.168.1.2", "192.168.1.3",  # gateways/routers
    "10.0.0.1", "10.0.0.2",                        # firewalls
    "10.0.1.1",                                     # DMZ router
    "192.168.1.53",                                 # internal DNS
    "192.168.1.100",                                # DHCP
]

# ── Attack family → (src_pool, dst_pool) mapping ─────────────────────────────
def _get_topology(label: str):
    """Map attack label to (source_pool, dest_pool) for realistic topology."""
    lbl = label.lower()

    if "benign" in lbl:
        return _WORKSTATIONS + _INFRA, _SERVERS + _INFRA + ["8.8.8.8", "1.1.1.1"]

    if "ddos" in lbl:
        # DDoS: many external attackers → few internal servers
        return _EXT_ATTACKERS, _SERVERS[:10]

    if "dos" in lbl:
        # DoS: fewer attackers, same victims
        return _EXT_ATTACKERS[:15], _SERVERS[:8]

    if "brute" in lbl or "dictionary" in lbl:
        # Brute force: external → SSH/services
        return _EXT_ATTACKERS[:10], _SERVERS[:5] + _INFRA[:3]

    if "scan" in lbl or "recon" in lbl or "vulnerability" in lbl:
        # Scanning: one or two attackers sweep many hosts
        return _EXT_ATTACKERS[:5], _SERVERS + _IOT[:15] + _WORKSTATIONS[:10]

    if "mirai" in lbl or "botnet" in lbl:
        # Mirai: compromised IoT → C2 servers externally
        return _IOT[:25], _EXT_ATTACKERS[:10]

    if "spoof" in lbl or "mitm" in lbl or "arp" in lbl:
        # Spoofing/MITM: internal lateral
        return _WORKSTATIONS[:10], _SERVERS[:5] + _INFRA[:3]

    if "xss" in lbl or "sql" in lbl or "injection" in lbl:
        # Web attacks: external → web servers
        return _EXT_ATTACKERS[:8], _SERVERS[:5]

    # Fallback: generic external → internal
    return _EXT_ATTACKERS[:15], _SERVERS[:10]


def _pick_ips(label: str, row_idx: int) -> tuple[str, str]:
    """Deterministically pick src/dst IPs based on label and row index."""
    src_pool, dst_pool = _get_topology(label)
    rng = random.Random(row_idx)
    return rng.choice(src_pool), rng.choice(dst_pool)


def _get_protocol(row: dict) -> str:
    """Extract protocol from CICIoT2023 binary indicator columns."""
    protos = ["TCP", "UDP", "ICMP", "HTTP", "HTTPS", "DNS", "SSH",
              "SMTP", "Telnet", "IRC", "DHCP", "ARP"]
    for col in protos:
        try:
            if float(row.get(col, 0)) > 0:
                return col
        except (TypeError, ValueError):
            continue
    # Fallback to Protocol Type numeric
    try:
        pt = int(float(row.get("Protocol Type", 6)))
        return {6: "TCP", 17: "UDP", 1: "ICMP"}.get(pt, "TCP")
    except (TypeError, ValueError):
        return "TCP"


def _is_private(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return False


def _safe_float(val, default=0.0) -> float:
    try:
        v = float(val)
        return v if (v == v and v != float("inf") and v != float("-inf")) else default
    except (TypeError, ValueError):
        return default


# ═══════════════════════════════════════════════════════════════════════════════
#  CONNECTION MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active_connections.append(ws)
        logger.info("WS client connected. Total=%d", len(self.active_connections))

    def disconnect(self, ws: WebSocket):
        if ws in self.active_connections:
            self.active_connections.remove(ws)
        logger.info("WS client disconnected. Total=%d", len(self.active_connections))

    async def broadcast(self, msg: dict):
        dead = []
        for conn in self.active_connections:
            try:
                await conn.send_json(msg)
            except Exception:
                dead.append(conn)
        for conn in dead:
            self.disconnect(conn)


manager    = ConnectionManager()


def _get_ml_manager():
    """Get the singleton ModelManager from the ml routes module."""
    from backend.api.routes.ml import get_model_manager
    return get_model_manager()


# ═══════════════════════════════════════════════════════════════════════════════
#  WEBSOCKET ENDPOINT
# ═══════════════════════════════════════════════════════════════════════════════

@router.websocket("/telemetry")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error("WebSocket error: %s", e)
        manager.disconnect(websocket)


# ═══════════════════════════════════════════════════════════════════════════════
#  TELEMETRY REPLAY LOOP
# ═══════════════════════════════════════════════════════════════════════════════

# Persistent node state — accumulated across all ticks
_node_threat_counts: dict[str, dict] = {}   # ip → {attacks: int, label: str, status: str}


def _update_node_state(ip: str, status: str, attack_type: str):
    """Track per-host cumulative threat state."""
    if ip not in _node_threat_counts:
        _node_threat_counts[ip] = {"attacks": 0, "label": "BenignTraffic", "status": "benign"}
    state = _node_threat_counts[ip]
    if status in ("attack", "suspicious"):
        state["attacks"] += 1
        state["label"] = attack_type
        state["status"] = status


async def mock_telemetry_stream():
    """
    Replay CICIoT2023 test.csv rows with deterministic IP synthesis and ML scoring.
    Builds a rich, persistent graph topology that accumulates over time.
    """
    logger.info("Loading telemetry dataset: %s", TEST_CSV)
    rows = load_dataset_with_fallback(TEST_CSV)
    logger.info("Telemetry ready — %d rows | replay=%.2fs", len(rows), REPLAY_INTERVAL)

    nodes_seen:     set[str] = set()
    active_threats: set[str] = set()
    edge_count = 0
    idx = 0

    while True:
        try:
            if not manager.active_connections:
                await asyncio.sleep(1)
                continue

            row = rows[idx % len(rows)]
            idx += 1

            # ── Synthesize topology ───────────────────────────────────────
            label      = row.get("label", "BenignTraffic")
            src_ip, dst_ip = _pick_ips(label, idx)
            protocol   = _get_protocol(row)

            nodes_seen.add(src_ip)
            nodes_seen.add(dst_ip)

            # ── ML scoring ────────────────────────────────────────────────
            node_data = {
                "id":       src_ip,
                "label":    f"Host {src_ip}",
                "features": row,
            }
            enriched = _get_ml_manager().score_node(node_data)

            status     = enriched.get("status", "benign")
            attack_type = enriched.get("attack_type", "BenignTraffic")
            
            # Record true label and evaluate correctness (kept for internal Neo4j logging)
            enriched["true_label"] = label
            enriched["is_correct"] = (label == attack_type)

            # Track host threat state
            _update_node_state(src_ip, status, attack_type)
            _update_node_state(dst_ip, "benign", "BenignTraffic")

            if status in ("suspicious", "attack", "critical"):
                active_threats.add(src_ip)

            is_lateral = _is_private(src_ip) and _is_private(dst_ip)
            rate       = _safe_float(row.get("Rate", 0))
            edge_count += 1

            # Keep attack_type, true_label, is_correct for frontend node-coloring & ML panel
            safe_enriched = {k: v for k, v in enriched.items() if k not in ("label",)}
            
            # Build destination node too
            dst_status = _node_threat_counts.get(dst_ip, {}).get("status", "benign")
            dst_node = {
                "id":    dst_ip,
                "label": f"Host {dst_ip}",
                "status": dst_status,
            }

            edges = [{
                "source":           src_ip,
                "target":           dst_ip,
                "protocol":         protocol,
                "suspicious":       status in ("suspicious", "attack", "critical"),
                "lateral_movement": is_lateral,
                "rate":             rate,
            }]

            # Async Neo4j (still receives the raw attack_type for logging/admin)
            asyncio.create_task(_neo4j_upsert(src_ip, dst_ip, edges[0], enriched))

            message = {
                "type":  "UPDATE",
                "nodes": [safe_enriched, dst_node],
                "edges": edges,
                "telemetry_event": {
                    "Protocol":    protocol,
                    "Rate":        row.get("Rate", "0"),
                    "src_ip":      src_ip,
                    "dst_ip":      dst_ip,
                    "status":      status,
                    "anomaly_score": enriched.get("anomaly_score", 0.0),
                    "confidence": enriched.get("confidence", 0.0),
                },
                "threat_summary": {
                    "flows":   edge_count,
                    "threats": len(active_threats),
                    "live":    True,
                },
                "timestamp": "",
            }

            await manager.broadcast(message)
            
            # Smooth node spawning to avoid bursty updates
            jitter = random.uniform(0.5, 1.5)
            await asyncio.sleep(REPLAY_INTERVAL * jitter)

        except Exception as e:
            logger.error("Telemetry stream error: %s", e, exc_info=True)
            await asyncio.sleep(5)


async def _neo4j_upsert(src_ip: str, dst_ip: str, edge: dict, node: dict):
    """Fire-and-forget Neo4j writes."""
    try:
        await neo4j_client.upsert_host(src_ip)
        await neo4j_client.upsert_host(dst_ip)
        if edge.get("suspicious"):
            await neo4j_client.write_attack_event(
                source_ip=src_ip,
                dest_ip=dst_ip,
                stage=node.get("attack_type", "unknown"),
                confidence=float(node.get("confidence", 0.0)),
                attack_label=node.get("status", "unknown"),
                ml_model="xgboost_iso_forest_hybrid",
            )
    except Exception as e:
        logger.debug("Neo4j write skipped: %s", e)
