"""Lightweight, dependency-free relationship graph for suspicious clusters."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Iterable

ENTITY_FIELDS = ("customer_id", "device_id", "ip_address", "card_fingerprint", "merchant_id")


@dataclass(frozen=True)
class GraphAnalysis:
    connected_entities: list[str]
    suspicious_clusters: list[dict]
    cluster_size: int
    shared_identifiers: dict[str, list[str]]
    risk_score: float
    explanation: str
    risk_type: str
    connected_accounts: int
    historical_disputed_value: float

    def to_dict(self) -> dict:
        return {
            "connected_entities": self.connected_entities,
            "suspicious_clusters": self.suspicious_clusters,
            "cluster_size": self.cluster_size,
            "shared_identifiers": self.shared_identifiers,
            "risk_score": self.risk_score,
            "explanation": self.explanation,
            "risk_type": self.risk_type,
            "connected_accounts": self.connected_accounts,
            "historical_disputed_value": self.historical_disputed_value,
        }


class RiskGraph:
    def __init__(self, rows: Iterable[dict] = ()):
        self.entity_to_nodes: dict[str, set[str]] = defaultdict(set)
        self.node_to_entities: dict[str, set[str]] = defaultdict(set)
        self.node_amounts: dict[str, float] = {}
        for row in rows:
            self.add(row)

    def add(self, row: dict) -> None:
        node = f"dispute:{row.get('dispute_id', 'unknown')}"
        try:
            self.node_amounts[row.get("dispute_id", "unknown")] = float(row.get("amount", 0.0) or 0.0)
        except (TypeError, ValueError):
            self.node_amounts[row.get("dispute_id", "unknown")] = 0.0
        # analyze() can inspect the row immediately even when it was not pre-added.
        for field in ENTITY_FIELDS:
            value = row.get(field)
            if value in (None, ""):
                continue
            entity = f"{field}:{value}"
            self.entity_to_nodes[entity].add(node)
            self.node_to_entities[node].add(entity)

    def analyze(self, row: dict) -> GraphAnalysis:
        self.add(row)
        node = f"dispute:{row.get('dispute_id', 'unknown')}"
        start_entities = self.node_to_entities.get(node, set())
        connected_nodes: set[str] = {node}
        queue = deque([node])
        while queue:
            current = queue.popleft()
            for entity in self.node_to_entities.get(current, set()):
                for neighbor in self.entity_to_nodes.get(entity, set()):
                    if neighbor not in connected_nodes:
                        connected_nodes.add(neighbor)
                        queue.append(neighbor)
        shared: dict[str, list[str]] = {}
        for entity in start_entities:
            nodes = self.entity_to_nodes.get(entity, set())
            if len(nodes) > 1:
                kind, value = entity.split(":", 1)
                shared.setdefault(kind, []).append(value)
        other_disputes = max(0, len(connected_nodes) - 1)
        shared_count = sum(len(v) for v in shared.values())
        risk_score = min(1.0, 0.10 * other_disputes + 0.15 * shared_count)
        connected_customers = set()
        historical_disputed_value = 0.0
        for related_node in connected_nodes:
            for entity in self.node_to_entities.get(related_node, set()):
                kind, value = entity.split(":", 1)
                if kind == "customer_id":
                    connected_customers.add(value)
            try:
                dispute_id = related_node.split(":", 1)[1]
                # Values are optionally attached to the node during add().
                historical_disputed_value += float(getattr(self, "node_amounts", {}).get(dispute_id, 0.0))
            except (ValueError, TypeError):
                pass
        risk_type = "ORGANIZED_ABUSE" if risk_score >= 0.60 else "SHARED_INFRASTRUCTURE" if risk_score > 0 else "NO_CLUSTER"
        clusters = []
        if other_disputes:
            clusters.append({"size": len(connected_nodes), "related_disputes": sorted(connected_nodes)})
        explanation = (
            "No connected risk cluster detected."
            if not clusters
            else f"Connected to {other_disputes} other dispute(s) through {shared_count} shared identifier(s)."
        )
        return GraphAnalysis(
            connected_entities=sorted(start_entities),
            suspicious_clusters=clusters,
            cluster_size=len(connected_nodes),
            shared_identifiers=shared,
            risk_score=risk_score,
            explanation=explanation,
            risk_type=risk_type,
            connected_accounts=len(connected_customers),
            historical_disputed_value=historical_disputed_value,
        )
