"""Tests for graph false-positive controls, entity weighting, and cluster boundaries."""
import pytest
from chargeback_risk_engine.engine.risk_graph import (
    RiskGraph,
    WEIGHT_STRONG_IDENTIFIER,
    WEIGHT_IP_ADDRESS,
    MAX_BFS_HOPS,
    MAX_EVALUATED_CLUSTER_NODES,
    GRAPH_ESCALATION_THRESHOLD,
    STRONG_IDENTIFIERS,
)


def test_module_level_named_constants_exist():
    assert WEIGHT_STRONG_IDENTIFIER == 1.0
    assert WEIGHT_IP_ADDRESS == 0.25
    assert MAX_BFS_HOPS == 2
    assert MAX_EVALUATED_CLUSTER_NODES == 50
    assert GRAPH_ESCALATION_THRESHOLD == 0.60
    assert "card_fingerprint" in STRONG_IDENTIFIERS
    assert "device_id" in STRONG_IDENTIFIERS
    assert "customer_id" in STRONG_IDENTIFIERS
    assert "ip_address" not in STRONG_IDENTIFIERS


def test_ten_unrelated_customers_on_one_ip_stay_below_escalation_threshold():
    """10 unrelated customers sharing only an IP address must not escalate to manual review."""
    shared_ip = "192.168.1.100"
    rows = [
        {
            "dispute_id": f"D_IP_{i}",
            "customer_id": f"cust_{i}",
            "device_id": f"dev_{i}",
            "card_fingerprint": f"card_{i}",
            "ip_address": shared_ip,
            "amount": 1500.0,
        }
        for i in range(10)
    ]
    graph = RiskGraph(rows)

    # Analyze the 10th dispute
    analysis = graph.analyze(rows[-1])
    assert analysis.risk_score < GRAPH_ESCALATION_THRESHOLD
    assert analysis.risk_type != "ORGANIZED_ABUSE"


def test_same_card_fingerprint_across_three_customers_escalates():
    """A single payment card shared across 3 distinct customer accounts must escalate to ORGANIZED_ABUSE."""
    shared_card = "card_compromised_ring_99"
    rows = [
        {
            "dispute_id": f"D_CARD_{i}",
            "customer_id": f"cust_victim_{i}",
            "device_id": f"dev_unique_{i}",
            "card_fingerprint": shared_card,
            "ip_address": f"10.0.0.{i}",
            "amount": 2500.0,
        }
        for i in range(3)
    ]
    graph = RiskGraph(rows)

    analysis = graph.analyze(rows[-1])
    assert analysis.risk_score >= GRAPH_ESCALATION_THRESHOLD
    assert analysis.risk_type == "ORGANIZED_ABUSE"
    assert analysis.connected_accounts == 3
    assert "card_fingerprint" in analysis.shared_identifiers


def test_weak_ip_link_between_two_separate_clusters_does_not_merge_them():
    """Two separate fraud rings (sharing device/card) that happen to hit the same public IP

    must NOT be merged into a single giant cluster.
    """
    # Cluster A: d1 and d2 share Device A
    # Cluster B: d3 and d4 share Device B
    # d2 and d3 share a public IP
    rows = [
        {
            "dispute_id": "D_A1",
            "customer_id": "cust_A1",
            "device_id": "device_ring_A",
            "card_fingerprint": "card_A1",
            "ip_address": "10.1.1.1",
            "amount": 1000.0,
        },
        {
            "dispute_id": "D_A2",
            "customer_id": "cust_A2",
            "device_id": "device_ring_A",
            "card_fingerprint": "card_A2",
            "ip_address": "192.168.1.1",  # Weak bridge IP
            "amount": 1000.0,
        },
        {
            "dispute_id": "D_B1",
            "customer_id": "cust_B1",
            "device_id": "device_ring_B",
            "card_fingerprint": "card_B1",
            "ip_address": "192.168.1.1",  # Weak bridge IP
            "amount": 1000.0,
        },
        {
            "dispute_id": "D_B2",
            "customer_id": "cust_B2",
            "device_id": "device_ring_B",
            "card_fingerprint": "card_B2",
            "ip_address": "10.2.2.2",
            "amount": 1000.0,
        },
    ]
    graph = RiskGraph(rows)

    # Analyzing D_A1 should only see Cluster A (D_A1, D_A2), NOT Cluster B (D_B1, D_B2)
    analysis = graph.analyze(rows[0])
    cluster_dispute_ids = set()
    for cluster in analysis.suspicious_clusters:
        for node in cluster["related_disputes"]:
            cluster_dispute_ids.add(node.replace("dispute:", ""))

    assert "D_A1" in cluster_dispute_ids or analysis.cluster_size == 2
    assert "D_B2" not in cluster_dispute_ids
    assert analysis.cluster_size <= 2


def test_merchant_only_sharing_never_changes_risk():
    """Merchant ID is a seller identifier and must never link unrelated buyer disputes."""
    rows = [
        {
            "dispute_id": f"D_MERCHANT_{i}",
            "merchant_id": "merchant_large_enterprise",
            "customer_id": f"cust_{i}",
            "device_id": f"dev_{i}",
            "card_fingerprint": f"card_{i}",
            "ip_address": f"172.16.0.{i}",
            "amount": 1200.0,
        }
        for i in range(12)
    ]
    graph = RiskGraph(rows)

    for row in rows:
        analysis = graph.analyze(row)
        assert analysis.cluster_size == 1
        assert analysis.risk_score == 0.0
        assert analysis.risk_type == "NO_CLUSTER"
        assert len(analysis.suspicious_clusters) == 0


def test_bfs_depth_is_capped_at_max_hops():
    """A long chain of strong identifiers A->B->C->D is capped at 2 hops from the query dispute."""
    rows = [
        {"dispute_id": "D_HOP_0", "customer_id": "cust_0", "device_id": "dev_0_1"},
        {"dispute_id": "D_HOP_1", "customer_id": "cust_1", "device_id": "dev_0_1", "card_fingerprint": "card_1_2"},
        {"dispute_id": "D_HOP_2", "customer_id": "cust_2", "card_fingerprint": "card_1_2", "device_id": "dev_2_3"},
        {"dispute_id": "D_HOP_3", "customer_id": "cust_3", "device_id": "dev_2_3", "card_fingerprint": "card_3_4"},
        {"dispute_id": "D_HOP_4", "customer_id": "cust_4", "card_fingerprint": "card_3_4"},
    ]
    graph = RiskGraph(rows, max_bfs_hops=2)

    analysis = graph.analyze(rows[0])
    # D_HOP_0 connects to D_HOP_1 (1 hop), D_HOP_1 connects to D_HOP_2 (2 hops).
    # D_HOP_3 (3 hops) and D_HOP_4 (4 hops) must not be included.
    cluster_dispute_ids = set()
    for c in analysis.suspicious_clusters:
        for n in c["related_disputes"]:
            cluster_dispute_ids.add(n.replace("dispute:", ""))
    assert "D_HOP_3" not in cluster_dispute_ids
    assert "D_HOP_4" not in cluster_dispute_ids
