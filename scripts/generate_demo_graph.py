#!/usr/bin/env python3
import asyncio
import uuid
from datetime import datetime, timedelta

from backend.graph.neo4j_client import neo4j_client

async def generate_demo_graph():
    print("Generating screenshot-friendly Neo4j topologies...")
    neo4j_client.connect()

    # Base timestamps
    now = datetime.utcnow()
    
    # Ensure protocols exist
    await neo4j_client.execute("MERGE (p:Protocol {name: 'TCP'})")
    await neo4j_client.execute("MERGE (p:Protocol {name: 'UDP'})")
    await neo4j_client.execute("MERGE (p:Protocol {name: 'HTTP'})")

    # Ensure attack labels exist
    attacks = [
        ("DDoS::SYN", "DDoS", "SYN", "DDoS"),
        ("BruteForce::SSH", "BruteForce", "SSH", "BruteForce"),
        ("Recon::PortScan", "Recon", "PortScan", "Recon"),
        ("Exploit::SQL_Injection", "Exploit", "SQL_Injection", "Exploit"),
        ("Malware::C2", "Malware", "C2", "Malware")
    ]
    for key, label, sublabel, cat in attacks:
        await neo4j_client.execute(
            """
            MERGE (a:Attack {attack_key: $key})
            SET a.label = $label, a.subLabel = $sublabel, a.subLabelCat = $cat
            """,
            {"key": key, "label": label, "sublabel": sublabel, "cat": cat}
        )

    # Helper function to create flows
    async def create_flow(src_ip, dst_ip, label, sublabel, protocol, count=1, attack_key=None, is_compromised=False):
        # Ensure hosts exist
        await neo4j_client.upsert_host(src_ip, role="attacker" if is_compromised else "workstation")
        await neo4j_client.upsert_host(dst_ip, role="server")

        if is_compromised:
            await neo4j_client.execute("MATCH (h:Host {ip: $ip}) SET h.compromise_status = 'compromised'", {"ip": src_ip})

        for i in range(count):
            flow_id = str(uuid.uuid4())
            ts = (now - timedelta(minutes=i)).isoformat()
            
            # Create Flow
            await neo4j_client.execute(
                """
                MATCH (src:Host {ip: $src_ip})
                MATCH (dst:Host {ip: $dst_ip})
                MATCH (p:Protocol {name: $protocol})
                CREATE (f:Flow {
                    flow_id: $flow_id, ts: $ts,
                    src_ip: $src_ip, dst_ip: $dst_ip,
                    label: $label, sublabel: $sublabel,
                    predicted_label: $sublabel,
                    confidence_score: 0.95
                })
                MERGE (src)-[:INITIATED {ts: $ts}]->(f)
                MERGE (f)-[:TARGETS {ts: $ts}]->(dst)
                MERGE (f)-[:USES_PROTOCOL {ts: $ts}]->(p)
                """,
                {
                    "src_ip": src_ip, "dst_ip": dst_ip, "protocol": protocol,
                    "flow_id": flow_id, "ts": ts,
                    "label": label, "sublabel": sublabel
                }
            )

            # Link to Attack if malicious
            if label == 'Malicious' and attack_key:
                await neo4j_client.execute(
                    """
                    MATCH (f:Flow {flow_id: $flow_id})
                    MATCH (a:Attack {attack_key: $attack_key})
                    MERGE (f)-[:HAS_ATTACK_TYPE {ts: $ts}]->(a)
                    """,
                    {"flow_id": flow_id, "attack_key": attack_key, "ts": ts}
                )

    # 1. DDoS Fan-out Cluster (Many flows, one attacker, one victim)
    print("Generating DDoS fan-out...")
    await create_flow("10.0.0.100", "192.168.1.21", "Malicious", "DDoS_SYN", "TCP", count=15, attack_key="DDoS::SYN", is_compromised=True)

    # 2. Multi-hop Lateral Movement
    print("Generating Lateral Movement chain...")
    await create_flow("10.0.0.200", "192.168.1.15", "Malicious", "BruteForce", "TCP", count=1, attack_key="BruteForce::SSH", is_compromised=True)
    # 192.168.1.15 is now compromised, attacks the DB
    await neo4j_client.execute("MATCH (h:Host {ip: '192.168.1.15'}) SET h.compromise_status = 'compromised'")
    await create_flow("192.168.1.15", "192.168.1.20", "Malicious", "SQL_Injection", "TCP", count=1, attack_key="Exploit::SQL_Injection", is_compromised=True)

    # 3. Suspicious Communication Cluster (Multiple internal hosts calling out to one C2)
    print("Generating C2 Cluster...")
    await create_flow("192.168.1.50", "8.8.4.4", "Malicious", "C2_Beacon", "HTTP", count=2, attack_key="Malware::C2", is_compromised=True)
    await create_flow("192.168.1.51", "8.8.4.4", "Malicious", "C2_Beacon", "HTTP", count=3, attack_key="Malware::C2", is_compromised=True)
    await create_flow("192.168.1.52", "8.8.4.4", "Malicious", "C2_Beacon", "HTTP", count=2, attack_key="Malware::C2", is_compromised=True)

    # 4. Mixed Attack Families
    print("Generating Mixed Attacks...")
    await create_flow("10.0.0.210", "192.168.1.22", "Malicious", "PortScan", "TCP", count=2, attack_key="Recon::PortScan", is_compromised=True)
    await create_flow("10.0.0.210", "192.168.1.22", "Malicious", "BruteForce", "TCP", count=3, attack_key="BruteForce::SSH", is_compromised=True)

    # Normal Background Traffic
    print("Generating benign background traffic...")
    await create_flow("192.168.1.10", "192.168.1.21", "Benign", "Normal", "HTTP", count=5)
    await create_flow("192.168.1.11", "192.168.1.21", "Benign", "Normal", "HTTP", count=3)

    print("Demo graph generation complete!")
    await neo4j_client.close()

if __name__ == "__main__":
    asyncio.run(generate_demo_graph())
