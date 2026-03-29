# graph_analysis.py
"""Build and analyze supply chain graph using NetworkX."""

import networkx as nx
from collections import defaultdict


def build_supply_chain_graph(records: list) -> nx.DiGraph:
    """Build a directed graph from sub-award records.

    - Nodes = companies (with attributes: total_received, total_awarded, is_prime, is_sub)
    - Edges = prime -> sub relationships (with attribute: total_amount)
    Returns nx.DiGraph
    """
    G = nx.DiGraph()

    # Aggregate edge weights and node attributes
    edge_amounts = defaultdict(float)
    node_received = defaultdict(float)  # amount received as sub
    node_awarded = defaultdict(float)   # amount awarded as prime
    prime_set = set()
    sub_set = set()

    for rec in records:
        prime = rec.get("prime_canonical") or rec.get("Prime Recipient Name", "")
        sub = rec.get("sub_canonical") or rec.get("Sub-Awardee Name", "")
        amount = rec.get("Sub-Award Amount", 0) or 0

        if not prime or not sub:
            continue
        if isinstance(amount, str):
            try:
                amount = float(amount.replace(",", ""))
            except ValueError:
                amount = 0
        amount = float(amount)

        prime_set.add(prime)
        sub_set.add(sub)
        edge_amounts[(prime, sub)] += amount
        node_awarded[prime] += amount
        node_received[sub] += amount

    # Add nodes
    all_companies = prime_set | sub_set
    for company in all_companies:
        G.add_node(
            company,
            total_received=node_received.get(company, 0),
            total_awarded=node_awarded.get(company, 0),
            is_prime=company in prime_set,
            is_sub=company in sub_set,
        )

    # Add edges
    for (prime, sub), amount in edge_amounts.items():
        G.add_edge(prime, sub, total_amount=amount)

    return G


def calculate_network_metrics(G: nx.DiGraph) -> dict:
    """Calculate key network metrics for each node:

    - in_degree: number of primes feeding this company
    - out_degree: number of subs this company feeds
    - betweenness_centrality: how critical is this node as a bridge
    - pagerank: overall importance in the network
    - hub_score / authority_score: HITS algorithm
    Returns dict: {company: {metrics}}
    """
    if len(G.nodes) == 0:
        return {}

    # Basic degree metrics
    in_deg = dict(G.in_degree())
    out_deg = dict(G.out_degree())

    # Betweenness centrality
    try:
        betweenness = nx.betweenness_centrality(G, weight="total_amount")
    except Exception:
        betweenness = {n: 0 for n in G.nodes}

    # PageRank
    try:
        pagerank = nx.pagerank(G, weight="total_amount", max_iter=200)
    except Exception:
        pagerank = {n: 1.0 / len(G.nodes) for n in G.nodes}

    # HITS
    try:
        hubs, authorities = nx.hits(G, max_iter=200)
    except Exception:
        hubs = {n: 0 for n in G.nodes}
        authorities = {n: 0 for n in G.nodes}

    metrics = {}
    for node in G.nodes:
        metrics[node] = {
            "in_degree": in_deg.get(node, 0),
            "out_degree": out_deg.get(node, 0),
            "betweenness_centrality": round(betweenness.get(node, 0), 6),
            "pagerank": round(pagerank.get(node, 0), 6),
            "hub_score": round(hubs.get(node, 0), 6),
            "authority_score": round(authorities.get(node, 0), 6),
            "total_received": G.nodes[node].get("total_received", 0),
            "total_awarded": G.nodes[node].get("total_awarded", 0),
            "is_prime": G.nodes[node].get("is_prime", False),
            "is_sub": G.nodes[node].get("is_sub", False),
        }

    return metrics


def simulate_risk_propagation(
    G: nx.DiGraph, failed_company: str, decay_factor: float = 0.7
) -> dict:
    """Simulate what happens when a company fails.

    - Direct subs lose (their edge weight / total incoming) * 100% risk
    - Risk propagates downstream with decay_factor at each level
    Returns dict: {company: risk_impact_score (0-100)}
    """
    if failed_company not in G:
        return {}

    risk = {}
    visited = set()
    queue = [(failed_company, 100.0, 0)]  # (node, risk_level, depth)

    while queue:
        current, current_risk, depth = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)

        if current != failed_company:
            risk[current] = round(min(current_risk, 100.0), 1)

        # Propagate to successors (subs of this company)
        for successor in G.successors(current):
            if successor in visited:
                continue
            edge_weight = G[current][successor].get("total_amount", 0)
            # Calculate dependency: what fraction of successor's incoming is from current
            total_incoming = sum(
                G[pred][successor].get("total_amount", 0)
                for pred in G.predecessors(successor)
            )
            if total_incoming > 0:
                dependency = edge_weight / total_incoming
            else:
                dependency = 0.5
            propagated_risk = current_risk * dependency * decay_factor
            if propagated_risk >= 1.0:  # Only propagate meaningful risk
                queue.append((successor, propagated_risk, depth + 1))

        # Also propagate to predecessors (primes that depend on this sub)
        for predecessor in G.predecessors(current):
            if predecessor in visited:
                continue
            edge_weight = G[predecessor][current].get("total_amount", 0)
            total_outgoing = sum(
                G[predecessor][succ].get("total_amount", 0)
                for succ in G.successors(predecessor)
            )
            if total_outgoing > 0:
                dependency = edge_weight / total_outgoing
            else:
                dependency = 0.5
            propagated_risk = current_risk * dependency * decay_factor * 0.5  # less upstream impact
            if propagated_risk >= 1.0:
                queue.append((predecessor, propagated_risk, depth + 1))

    return risk


def get_critical_path(G: nx.DiGraph, company: str) -> list:
    """Find the most critical supply chain path through a company.

    Returns list of companies in the critical path.
    """
    if company not in G:
        return [company]

    # Find the longest weighted path passing through this node
    # Walk upstream (predecessors) picking heaviest edges
    upstream = []
    current = company
    visited = {company}
    for _ in range(10):  # max depth
        preds = list(G.predecessors(current))
        preds = [p for p in preds if p not in visited]
        if not preds:
            break
        # Pick the predecessor with the heaviest edge
        best = max(preds, key=lambda p: G[p][current].get("total_amount", 0))
        upstream.insert(0, best)
        visited.add(best)
        current = best

    # Walk downstream (successors) picking heaviest edges
    downstream = []
    current = company
    for _ in range(10):  # max depth
        succs = list(G.successors(current))
        succs = [s for s in succs if s not in visited]
        if not succs:
            break
        best = max(succs, key=lambda s: G[current][s].get("total_amount", 0))
        downstream.append(best)
        visited.add(best)
        current = best

    return upstream + [company] + downstream


def get_company_ego_network(G: nx.DiGraph, company: str, radius: int = 2) -> nx.DiGraph:
    """Get the local network around a company (radius hops).

    Returns subgraph for visualization.
    """
    if company not in G:
        return nx.DiGraph()

    # Get nodes within radius hops (both directions)
    nodes = {company}
    frontier = {company}
    for _ in range(radius):
        next_frontier = set()
        for node in frontier:
            next_frontier.update(G.successors(node))
            next_frontier.update(G.predecessors(node))
        frontier = next_frontier - nodes
        nodes.update(frontier)

    return G.subgraph(nodes).copy()
