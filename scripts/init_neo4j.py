#!/usr/bin/env python3
import argparse
import asyncio
import csv
from pathlib import Path

from backend.graph.neo4j_client import neo4j_client
from backend.graph.schema_manager import SchemaManager


SAMPLE_HOSTS = [
    ("192.168.1.10", "workstation-1", "engineering"),
    ("192.168.1.11", "workstation-2", "engineering"),
    ("192.168.1.20", "server-db-1", "database"),
    ("192.168.1.21", "server-web-1", "web"),
    ("192.168.1.22", "server-dc-1", "domain_controller"),
    ("192.168.1.100", "iot-sensor-1", "iot"),
    ("192.168.1.101", "iot-sensor-2", "iot"),
    ("192.168.1.200", "gateway-1", "gateway"),
    ("10.0.0.1", "firewall-1", "firewall"),
    ("10.0.0.2", "ids-1", "ids"),
]


async def init_schema(manager: SchemaManager) -> None:
    print("Initializing Neo4j schema...")
    await manager.full_init()
    print("Schema initialization complete")


def get_dataset_files(data_dir: Path) -> list[Path]:
    """Return ordered list of CICIoT2023 CSVs: train, validation, test."""
    known_paths = [
        data_dir / "train"      / "train.csv",
        data_dir / "validation" / "validation.csv",
        data_dir / "test"       / "test.csv",
    ]
    return [p for p in known_paths if p.exists()]


async def seed_hosts_from_dataset(csv_paths: list[str] | None = None) -> int:
    if csv_paths is None:
        data_dir = Path(__file__).parent.parent / "data"

        if data_dir.exists():
            csv_files = get_dataset_files(data_dir)
            csv_paths = [str(f) for f in csv_files if f.exists()]
        else:
            csv_paths = []

    if not csv_paths:
        print("No datasets found, creating sample hosts...")
        return await _create_sample_hosts()

    total = 0

    for csv_path in csv_paths:
        count = await _seed_from_single_csv(csv_path)
        total += count
        print(f"Seeded {count} hosts from {Path(csv_path).name}")

    print(f"Total hosts seeded: {total}")
    return total


async def _seed_from_single_csv(csv_path: str, batch_size: int = 500) -> int:
    seen_ips = set()
    batch = []
    total = 0

    try:
        with open(csv_path, "r", encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f)

            for row in reader:
                src_ip = row.get("Source IP", "").strip()
                dst_ip = row.get("Destination IP", "").strip()

                for ip in [src_ip, dst_ip]:
                    if ip and ip not in seen_ips and _is_valid_ip(ip):
                        seen_ips.add(ip)
                        batch.append((ip, _infer_hostname(ip), _infer_role(ip)))

                        if len(batch) >= batch_size:
                            await _batch_upsert_hosts(batch)
                            total += len(batch)
                            batch = []

        if batch:
            await _batch_upsert_hosts(batch)
            total += len(batch)

    except Exception as e:
        print(f"CSV seeding failed: {csv_path} -> {e}")

    return total


async def _batch_upsert_hosts(hosts: list[tuple]) -> None:
    tasks = [
        neo4j_client.upsert_host(ip, hostname, role)
        for ip, hostname, role in hosts
    ]
    await asyncio.gather(*tasks)


async def _create_sample_hosts() -> int:
    tasks = [
        neo4j_client.upsert_host(ip, hostname, role)
        for ip, hostname, role in SAMPLE_HOSTS
    ]

    await asyncio.gather(*tasks)

    print(f"Sample hosts created: {len(SAMPLE_HOSTS)}")
    return len(SAMPLE_HOSTS)


def _is_valid_ip(ip: str) -> bool:
    parts = ip.split(".")
    if len(parts) != 4:
        return False

    try:
        return all(0 <= int(p) <= 255 for p in parts)
    except ValueError:
        return False


def _infer_hostname(ip: str) -> str:
    return f"host-{ip.split('.')[-1]}" if ip else ip


def _infer_role(ip: str) -> str:
    if ip.startswith("192.168.1.20"):
        return "database"
    elif ip.startswith("192.168.1.21"):
        return "web"
    elif ip.startswith("192.168.1.22"):
        return "domain_controller"
    elif ip.startswith("192.168.1."):
        return "workstation"
    elif ip.startswith("10.0.0."):
        return "internal"
    return "unknown"


# ✅ FIXED ASSET SEEDING
async def seed_high_value_assets() -> int:
    assets = [
        ("AST-001", "Database Server Alpha", "192.168.1.20", "db_server", "critical"),
        ("AST-002", "Domain Controller", "192.168.1.22", "domain_controller", "critical"),
        ("AST-003", "Web Server Prod", "192.168.1.21", "web_server", "high"),
    ]

    query = """
    MERGE (h:Host {ip: $ip})
    MERGE (a:Asset {asset_id: $asset_id})
    SET a.name = $name,
        a.ip = $ip,
        a.asset_type = $asset_type,
        a.criticality = $criticality
    MERGE (a)-[:ASSET_OF]->(h)
    """

    for asset_id, name, ip, asset_type, criticality in assets:
        await neo4j_client.execute(
            query,
            {
                "asset_id": asset_id,
                "name": name,
                "ip": ip,
                "asset_type": asset_type,
                "criticality": criticality,
            },
        )

    print(f"High value assets seeded: {len(assets)}")
    return len(assets)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema-only", action="store_true")
    parser.add_argument("--hosts-only", action="store_true")
    parser.add_argument("--dataset", type=str, nargs="+")
    args = parser.parse_args()

    neo4j_client.connect()
    manager = SchemaManager()

    try:
        if not args.hosts_only:
            await init_schema(manager)

        if not args.schema_only:
            host_count = await seed_hosts_from_dataset(args.dataset)
            asset_count = await seed_high_value_assets()

            print(f"Initialization complete: hosts={host_count}, assets={asset_count}")

    finally:
        await neo4j_client.close()


if __name__ == "__main__":
    asyncio.run(main())