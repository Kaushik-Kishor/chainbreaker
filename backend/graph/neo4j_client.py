import uuid
from datetime import datetime
from typing import Any

from neo4j import AsyncGraphDatabase, AsyncDriver

from backend.utils.config import config


class Neo4jClient:
    _instance = None
    _driver: AsyncDriver | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def connect(self) -> None:
        if self._driver is not None:
            return

        import os
        # Env var (set by docker-compose) takes precedence over YAML config
        uri      = os.environ.get("NEO4J_URI")      or config.get("neo4j.uri",      "bolt://neo4j:7687")
        user     = os.environ.get("NEO4J_USER")     or config.get("neo4j.user",     "neo4j")
        password = os.environ.get("NEO4J_PASSWORD") or config.get("neo4j.password", "chainbreaker")

        self._driver = AsyncGraphDatabase.driver(
            uri,
            auth=(user, password),
            max_connection_lifetime=3600,
        )

        print(f"Neo4j connected: {uri}")

    async def close(self) -> None:
        if self._driver:
            await self._driver.close()
            self._driver = None
            print("Neo4j disconnected")

    # ✅ FIXED: no contextmanager, direct async session
    async def execute(
        self,
        query: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        params = params or {}

        if self._driver is None:
            self.connect()

        database = config.get("neo4j.database", "neo4j")

        async with self._driver.session(database=database) as session:
            result = await session.run(query, params)
            records = await result.data()
            await result.consume()
            return records

    # =========================
    # DOMAIN METHODS
    # =========================

    async def upsert_host(
        self,
        ip: str,
        hostname: str | None = None,
        role: str = "unknown",
    ) -> str:
        query = """
        MERGE (h:Host {ip: $ip})
        ON CREATE SET
            h.host_id = $host_id,
            h.hostname = $hostname,
            h.role = $role,
            h.first_seen = $now,
            h.last_seen = $now
        ON MATCH SET
            h.hostname = COALESCE($hostname, h.hostname),
            h.role = COALESCE($role, h.role),
            h.last_seen = $now
        RETURN h.host_id AS host_id
        """

        host_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()

        records = await self.execute(
            query,
            {
                "ip": ip,
                "host_id": host_id,
                "hostname": hostname or ip,
                "role": role,
                "now": now,
            },
        )

        return records[0]["host_id"] if records else host_id

    async def execute_write(
        self,
        query: str,
        params: dict[str, Any] | None = None,
    ) -> None:
        await self.execute(query, params)

    async def write_attack_event(
        self,
        source_ip: str,
        dest_ip: str,
        stage: str,
        confidence: float,
        attack_label: str,
        ml_model: str,
    ) -> str:
        event_id = str(uuid.uuid4())
        ts = datetime.utcnow().isoformat()

        query = """
        MATCH (src:Host {ip: $source_ip})
        MATCH (dst:Host {ip: $dest_ip})
        CREATE (e:AttackEvent {
            event_id: $event_id,
            stage: $stage,
            timestamp: $timestamp,
            confidence: $confidence,
            source_ip: $source_ip,
            dest_ip: $dest_ip,
            attack_label: $attack_label,
            ml_model: $ml_model
        })
        CREATE (src)-[:SOURCE_OF]->(e)
        CREATE (e)-[:ON_HOST]->(dst)
        RETURN e.event_id AS event_id
        """

        await self.execute(
            query,
            {
                "event_id": event_id,
                "stage": stage,
                "timestamp": ts,
                "confidence": confidence,
                "source_ip": source_ip,
                "dest_ip": dest_ip,
                "attack_label": attack_label,
                "ml_model": ml_model,
            },
        )

        return event_id

    async def link_communicates_with(
        self,
        src_ip: str,
        dst_ip: str,
    ) -> None:
        query = """
        MATCH (src:Host {ip: $src_ip})
        MATCH (dst:Host {ip: $dst_ip})
        MERGE (src)-[:COMMUNICATES_WITH]->(dst)
        """

        await self.execute(query, {"src_ip": src_ip, "dst_ip": dst_ip})


neo4j_client = Neo4jClient()