"""
features.py — Single source of truth for feature definitions.

Both train.py and inference.py import from here so column sets
are never out of sync between training and serving.

Designed for the CICIoT2023 dataset which has 46 numeric features
and a single `label` column with 34 multiclass attack categories.
"""

# ── Columns to NEVER use as features ─────────────────────────────────────────
DROP_COLUMNS: list[str] = [
    "label",            # target column
]

# ── Target column ─────────────────────────────────────────────────────────────
# CICIoT2023 uses a single `label` column with string attack names.
# NOT `subLabelCat` (which doesn't exist in this dataset).
TARGET_COLUMN: str = "label"

# ── Feature groups ────────────────────────────────────────────────────────────
# These match the exact columns present in CICIoT2023 train/test/validation CSVs.

FLOW_METRICS: list[str] = [
    "flow_duration",
    "Header_Length",
    "Duration",
    "Rate",
    "Srate",
    "Drate",
]

TCP_FLAGS: list[str] = [
    "fin_flag_number",
    "syn_flag_number",
    "rst_flag_number",
    "psh_flag_number",
    "ack_flag_number",
    "ece_flag_number",
    "cwr_flag_number",
]

FLAG_COUNTS: list[str] = [
    "ack_count",
    "syn_count",
    "fin_count",
    "urg_count",
    "rst_count",
]

PROTOCOL_INDICATORS: list[str] = [
    "HTTP",
    "HTTPS",
    "DNS",
    "Telnet",
    "SMTP",
    "SSH",
    "IRC",
    "TCP",
    "UDP",
    "DHCP",
    "ARP",
    "ICMP",
    "IPv",
    "LLC",
]

PACKET_STATS: list[str] = [
    "Tot sum",
    "Min",
    "Max",
    "AVG",
    "Std",
    "Tot size",
    "IAT",
    "Number",
]

STATISTICAL_FEATURES: list[str] = [
    "Magnitue",     # dataset typo — keep as-is to match raw column name
    "Radius",
    "Covariance",
    "Variance",
    "Weight",
]

# ── Master feature list (used by both train and inference) ────────────────────
FEATURE_COLUMNS: list[str] = (
    FLOW_METRICS
    + TCP_FLAGS
    + FLAG_COUNTS
    + PROTOCOL_INDICATORS
    + PACKET_STATS
    + STATISTICAL_FEATURES
)

# ── Validation ────────────────────────────────────────────────────────────────
def validate_features(df_columns: list[str]) -> None:
    """
    Fail loudly if any label-related columns leak into the feature set.
    """
    forbidden = {"label", "subLabel", "subLabelCat", "attack_type", "status"}
    leaks = [col for col in df_columns if col.lower() in forbidden or col in forbidden]
    if leaks:
        raise ValueError(f"CRITICAL ERROR: Label leakage detected in features! Forbidden columns found: {leaks}")


# ── Label normalization ───────────────────────────────────────────────────────
BENIGN_LABEL: str = "BenignTraffic"


def normalize_label(raw_value) -> str:
    """
    Normalize label values from CICIoT2023.

    The dataset uses string attack names directly (e.g. "DDoS-TCP_Flood").
    BenignTraffic is the benign class string.
    """
    if raw_value is None:
        return BENIGN_LABEL
    s = str(raw_value).strip()
    if s in ("", "nan", "NaN"):
        return BENIGN_LABEL
    return s
