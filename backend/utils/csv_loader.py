"""
csv_loader.py — Centralized, robust CSV loading utility for ChainBreaker.

CICIoT2023 schema note: this dataset does NOT include Source IP / Destination IP
columns — it is an anonymized, pre-aggregated flow dataset.
IP addresses are synthesized by ws.py based on label and protocol to create
graph topology.

Usage:
    from backend.utils.csv_loader import safe_read_csv, load_dataset_with_fallback
"""

from __future__ import annotations

import csv
import os
import random

from backend.utils.logger import setup_logger

log = setup_logger("csv_loader")

# Ordered list of encodings to try
_ENCODINGS = ["utf-8", "utf-8-sig", "utf-16", "utf-16le", "latin1", "cp1252"]

# The minimum column that MUST exist for the dataset to be usable
_REQUIRED_COLUMNS = {"label"}

# Maximum rows to load into memory from the large CICIoT2023 files
# 332MB test.csv with ~2M rows — cap at 50k for healthy memory usage
MAX_ROWS = int(os.environ.get("TELEMETRY_MAX_ROWS", "50000"))

# CICIoT2023 attack label pool for synthetic fallback
_SYNTH_ATTACKS = [
    ("BenignTraffic",  "BenignTraffic",  "BenignTraffic"),
    ("DDoS-TCP",       "DDoS-TCP",       "ddos"),
    ("DDoS-UDP",       "DDoS-UDP",       "ddos"),
    ("DoS-UDP",        "DoS-UDP",        "dos"),
    ("PortScan",       "PortScan",       "scan"),
    ("BruteForce-SSH", "SSH-BruteForce", "bruteforce"),
    ("Mirai",          "Mirai-Flooding", "mirai"),
    ("Recon-PingSweep","Recon",          "recon"),
]
_PROTOS = ["TCP", "UDP", "ICMP", "HTTP", "DNS", "HTTPS"]


def safe_read_csv(path: str, max_rows: int = MAX_ROWS) -> list[dict]:
    """
    Robustly read a CSV by trying multiple encodings.

    Only loads up to `max_rows` rows to keep memory usage bounded even for
    the large CICIoT2023 files (train=1.6GB, test=332MB).

    Returns:
        List of dicts (csv.DictReader rows)

    Raises:
        RuntimeError if all encodings fail or no required columns found
    """
    abs_path = os.path.abspath(path)

    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"Dataset not found: {abs_path}")

    last_error: Exception | None = None

    for encoding in _ENCODINGS:
        try:
            log.info("Attempting to read '%s' with encoding '%s' (max_rows=%d) ...",
                     path, encoding, max_rows)
            rows: list[dict] = []
            with open(abs_path, "r", encoding=encoding, errors="strict") as f:
                reader = csv.DictReader(f)
                for i, row in enumerate(reader):
                    if max_rows > 0 and i >= max_rows:
                        break
                    rows.append(row)

            if not rows:
                raise ValueError("CSV contains 0 rows.")

            # Validate required columns
            actual_cols = set(rows[0].keys())
            missing = _REQUIRED_COLUMNS - actual_cols
            if missing:
                raise ValueError(
                    f"Missing required columns {missing}. Found: {sorted(actual_cols)}"
                )

            # ── Logging ────────────────────────────────────────────────────────
            log.info(
                "Loaded '%s' | encoding=%s | rows=%d | columns=%d",
                path, encoding, len(rows), len(rows[0]),
            )

            label_dist: dict[str, int] = {}
            for r in rows:
                lbl = r.get("label", "unknown")
                label_dist[lbl] = label_dist.get(lbl, 0) + 1
            top_labels = sorted(label_dist.items(), key=lambda x: -x[1])[:10]
            log.info("Label distribution (top-10): %s", dict(top_labels))
            log.info("Unique attack types: %d", len(label_dist))

            return rows

        except (UnicodeDecodeError, UnicodeError) as e:
            log.warning("Encoding '%s' failed: %s", encoding, e)
            last_error = e
            continue
        except Exception as e:
            log.error("Error reading '%s' with '%s': %s", path, encoding, e)
            last_error = e
            break

    raise RuntimeError(
        f"Failed to load '{path}' with all encodings {_ENCODINGS}. Last error: {last_error}"
    )


def generate_synthetic_rows(n: int = 500) -> list[dict]:
    """
    Generate synthetic rows that match the CICIoT2023 numeric feature schema.
    Used as fallback when the real dataset cannot be loaded.
    """
    log.warning("Using SYNTHETIC telemetry fallback (%d rows).", n)
    rows = []
    for _ in range(n):
        attack = random.choice(_SYNTH_ATTACKS)
        label, sublabel, sublabelcat = attack
        is_attack = label != "BenignTraffic"
        proto = random.choice(_PROTOS)

        rows.append({
            "flow_duration":    str(round(random.uniform(0.001, 120.0), 4)),
            "Header_Length":    str(random.randint(20, 1500)),
            "Protocol Type":    str(random.choice([6, 17, 1])),
            "Duration":         str(round(random.uniform(0, 120), 4)),
            "Rate":             str(round(random.uniform(100, 50000) if is_attack else random.uniform(1, 500), 2)),
            "Srate":            str(round(random.uniform(1, 25000), 2)),
            "Drate":            str(round(random.uniform(1, 25000), 2)),
            "fin_flag_number":  str(random.randint(0, 5)),
            "syn_flag_number":  str(random.randint(0, 500) if is_attack else random.randint(0, 3)),
            "rst_flag_number":  str(random.randint(0, 10)),
            "psh_flag_number":  str(random.randint(0, 5)),
            "ack_flag_number":  str(random.randint(0, 50)),
            "ece_flag_number":  "0",
            "cwr_flag_number":  "0",
            "urg_flag_number":  "0",
            "ack_count":        str(random.randint(0, 200)),
            "syn_count":        str(random.randint(0, 500) if is_attack else random.randint(0, 5)),
            "fin_count":        str(random.randint(0, 20)),
            "urg_count":        "0",
            "rst_count":        str(random.randint(0, 30)),
            "HTTP":             str(1 if proto == "HTTP" else 0),
            "HTTPS":            str(1 if proto == "HTTPS" else 0),
            "DNS":              str(1 if proto == "DNS" else 0),
            "Telnet":           "0",
            "SMTP":             "0",
            "SSH":              "0",
            "IRC":              "0",
            "TCP":              str(1 if proto == "TCP" else 0),
            "UDP":              str(1 if proto == "UDP" else 0),
            "DHCP":             "0",
            "ARP":              "0",
            "ICMP":             str(1 if proto == "ICMP" else 0),
            "IPv":              "0",
            "LLC":              "0",
            "CoAP":             "0",
            "Tot sum":          str(round(random.uniform(0, 100000), 2)),
            "Min":              str(round(random.uniform(0, 1000), 2)),
            "Max":              str(round(random.uniform(0, 100000), 2)),
            "AVG":              str(round(random.uniform(0, 50000), 2)),
            "Std":              str(round(random.uniform(0, 10000), 2)),
            "Tot size":         str(random.randint(40, 65535)),
            "IAT":              str(round(random.uniform(0, 1000), 4)),
            "Number":           str(random.randint(1, 1000)),
            "Magnitue":         str(round(random.uniform(0, 1000), 2)),
            "Radius":           str(round(random.uniform(0, 500), 2)),
            "Covariance":       str(round(random.uniform(-100, 100), 4)),
            "Variance":         str(round(random.uniform(0, 10000), 4)),
            "Weight":           str(round(random.uniform(0, 1), 6)),
            "label":            label,
            "subLabel":         sublabel,
            "subLabelCat":      sublabelcat,
            # Synthesized network fields for graph building
            "_proto_name":      proto,
        })
    return rows


def load_dataset_with_fallback(path: str, max_rows: int = MAX_ROWS) -> list[dict]:
    """
    Load a real CSV with encoding fallback.
    If it fails for any reason, return synthetic rows.
    Never raises — always returns usable telemetry.
    """
    try:
        return safe_read_csv(path, max_rows=max_rows)
    except Exception as e:
        log.error("Dataset load failed for '%s': %s. Using synthetic fallback.", path, e)
        return generate_synthetic_rows(n=500)
