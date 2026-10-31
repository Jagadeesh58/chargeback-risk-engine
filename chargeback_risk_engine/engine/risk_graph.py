"""Lightweight, dependency-free relationship graph for suspicious clusters."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Iterable

# Module-level named constants for false-positive and graph abuse control
WEIGHT_STRONG_IDENTIFIER = 1.0
WEIGHT_IP_ADDRESS = 0.25
MAX_BFS_HOPS = 2
MAX_EVALUATED_CLUSTER_NODES = 50
IP_MAX_DISTINCT_CUSTOMERS_FOR_RISK = 5
GRAPH_ESCALATION_THRESHOLD = 0.60

STRONG_IDENTIFIERS = frozenset({"customer_id", "device_id", "card_fingerprint"})
# Buyer-side identifiers only. merchant_id must not link unrelated buyer disputes.
ENTITY_FIELDS = ("customer_id", "device_id", "ip_address", "card_fingerprint")


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
    def __init__(
        self,
        rows: Iterable[dict] = (),
        max_hub_degree: int = 20,
        max_bfs_hops: int = MAX_BFS_HOPS,
        max_evaluated_cluster_nodes: int = MAX_EVALUATED_CLUSTER_NODES,
        ip_max_distinct_customers: int = IP_MAX_DISTINCT_CUSTOMERS_FOR_RISK,
    ):
        self.max_hub_degree = max_hub_degree
        self.max_bfs_hops = max_bfs_hops
        self.max_evaluated_cluster_nodes = max_evaluated_cluster_nodes
        self.ip_max_distinct_customers = ip_max_distinct_customers
        self.entity_to_nodes: dict[str, set[str]] = defaultdict(set)
        self.node_to_entities: dict[str, set[str]] = defaultdict(set)
        self.node_amounts: dict[str, float] = {}
        for row in rows:
            self.add(row)

    def clone(self) -> RiskGraph:
        """Return an independent copy with isolated node and entity indexes."""
        g = RiskGraph(
            max_hub_degree=self.max_hub_degree,
            max_bfs_hops=self.max_bfs_hops,
            max_evaluated_cluster_nodes=self.max_evaluated_cluster_nodes,
            ip_max_distinct_customers=self.ip_max_distinct_customers,
        )
        g.entity_to_nodes = defaultdict(set, {k: set(v) for k, v in self.entity_to_nodes.items()})
        g.node_to_entities = defaultdict(set, {k: set(v) for k, v in self.node_to_entities.items()})
        g.node_amounts = dict(self.node_amounts)
        return g

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
        queue = deque([(node, 0)])

        while queue and len(connected_nodes) < self.max_evaluated_cluster_nodes:
            current, depth = queue.popleft()
            if depth >= self.max_bfs_hops:
                continue

            current_entities = self.node_to_entities.get(current, set())
            for entity in current_entities:
                nodes_with_entity = self.entity_to_nodes.get(entity, set())
                # Hub degree capping: do not expand through high-degree benign hubs (e.g. ISP NAT)
                if len(nodes_with_entity) > self.max_hub_degree:
                    continue

                kind = entity.split(":", 1)[0]
                if kind == "ip_address":
                    # Distinct customers on this IP across all nodes
                    distinct_customers = {
                        e.split(":", 1)[1]
                        for n in nodes_with_entity
                        for e in self.node_to_entities.get(n, set())
                        if e.startswith("customer_id:")
                    }
                    for neighbor in nodes_with_entity:
                        if neighbor in connected_nodes:
                            continue
                        neighbor_entities = self.node_to_entities.get(neighbor, set())
                        shares_strong = bool(
                            {e for e in neighbor_entities if e.split(":", 1)[0] in STRONG_IDENTIFIERS}
                            & {e for e in current_entities if e.split(":", 1)[0] in STRONG_IDENTIFIERS}
                        )
                        # Weak IP link protection: do not bridge separate clusters over IP alone
                        if not shares_strong:
                            if depth >= 1 or len(distinct_customers) > self.ip_max_distinct_customers:
                                continue
                        connected_nodes.add(neighbor)
                        next_depth = depth + 1 if shares_strong else self.max_bfs_hops
                        queue.append((neighbor, next_depth))
                        if len(connected_nodes) >= self.max_evaluated_cluster_nodes:
                            break
                else:
                    # Strong identifier traversal
                    for neighbor in nodes_with_entity:
                        if neighbor not in connected_nodes:
                            connected_nodes.add(neighbor)
                            queue.append((neighbor, depth + 1))
                            if len(connected_nodes) >= self.max_evaluated_cluster_nodes:
                                break

        shared: dict[str, list[str]] = {}
        for entity in start_entities:
            nodes = self.entity_to_nodes.get(entity, set())
            if 1 < len(nodes) <= self.max_hub_degree:
                kind, value = entity.split(":", 1)
                shared.setdefault(kind, []).append(value)

        other_disputes = max(0, len(connected_nodes) - 1)
        connected_customers = set()
        historical_disputed_value = 0.0
        for related_node in connected_nodes:
            for entity in self.node_to_entities.get(related_node, set()):
                kind, value = entity.split(":", 1)
                if kind == "customer_id":
                    connected_customers.add(value)
            try:
                dispute_id = related_node.split(":", 1)[1]
                historical_disputed_value += float(getattr(self, "node_amounts", {}).get(dispute_id, 0.0))
            except (ValueError, TypeError):
                pass

        strong_shared_count = sum(len(shared.get(k, [])) for k in STRONG_IDENTIFIERS)
        ip_shared_count = len(shared.get("ip_address", []))

        # Check distinct customers on the shared IP
        ip_distinct_customers = 0
        if ip_shared_count > 0:
            for ip_val in shared.get("ip_address", []):
                ip_entity = f"ip_address:{ip_val}"
                ip_nodes = self.entity_to_nodes.get(ip_entity, set())
                custs = {
                    e.split(":", 1)[1]
                    for n in ip_nodes
                    for e in self.node_to_entities.get(n, set())
                    if e.startswith("customer_id:")
                }
                ip_distinct_customers = max(ip_distinct_customers, len(custs))

        # ip_address counts at reduced weight and only toward risk if at least one strong
        # identifier is also shared or IP is shared by <= N distinct customers.
        ip_counts_for_risk = (
            ip_shared_count > 0 and (
                strong_shared_count > 0 or ip_distinct_customers <= self.ip_max_distinct_customers
            )
        )
        effective_ip_weight = WEIGHT_IP_ADDRESS if ip_counts_for_risk else 0.0

        # Weighted identifier contribution
        weighted_id_score = (
            WEIGHT_STRONG_IDENTIFIER * 0.20 * strong_shared_count
            + effective_ip_weight * 0.15 * ip_shared_count
        )

        # Cross-account sharing is highly suspicious when linked by strong identifiers
        if len(connected_customers) > 1 and strong_shared_count > 0:
            cross_account_boost = 0.25 if "card_fingerprint" in shared else 0.15
        elif len(connected_customers) > 1 and ip_counts_for_risk:
            cross_account_boost = 0.05
        else:
            cross_account_boost = 0.0

        if strong_shared_count == 0 and not ip_counts_for_risk:
            effective_dispute_count = 0
        else:
            effective_dispute_count = other_disputes

        risk_score = min(1.0, 0.15 * effective_dispute_count + weighted_id_score + cross_account_boost)
        risk_type = "ORGANIZED_ABUSE" if risk_score >= GRAPH_ESCALATION_THRESHOLD else "SHARED_INFRASTRUCTURE" if risk_score > 0 else "NO_CLUSTER"
        clusters = []
        if other_disputes:
            clusters.append({"size": len(connected_nodes), "related_disputes": sorted(connected_nodes)})
        explanation = (
            "No connected risk cluster detected."
            if not clusters
            else f"Connected to {other_disputes} other dispute(s) through {len(shared)} shared identifier type(s)."
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
