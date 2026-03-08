"""Verify OR-Tools SimpleMinCostFlow works as expected.

Solves a tiny min-cost flow: 2 sources, 2 sinks, 1 null node.
This is the pattern used by the transport applications.

Usage: uv run python -m enrichment.test_ortools
"""

import logging

from ortools.graph.python import min_cost_flow

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    smcf = min_cost_flow.SimpleMinCostFlow()

    # Nodes: 0=super_source, 1=super_sink, 2=null, 3=src_A, 4=src_B, 5=tgt_X, 6=tgt_Y
    SUPER_SOURCE, SUPER_SINK, NULL = 0, 1, 2
    SRC_A, SRC_B, TGT_X, TGT_Y = 3, 4, 5, 6

    total_demand = 5  # tgt_X wants 3, tgt_Y wants 2

    # super_source -> sources (capacity = supply, cost = 0)
    smcf.add_arc_with_capacity_and_unit_cost(SUPER_SOURCE, SRC_A, 2, 0)  # A supplies 2
    smcf.add_arc_with_capacity_and_unit_cost(SUPER_SOURCE, SRC_B, 2, 0)  # B supplies 2

    # super_source -> null (capacity = total_demand, cost = 0)
    smcf.add_arc_with_capacity_and_unit_cost(SUPER_SOURCE, NULL, total_demand, 0)

    # sources -> targets (bipartite, cost = 1 for strong match)
    smcf.add_arc_with_capacity_and_unit_cost(SRC_A, TGT_X, 2, 1)
    smcf.add_arc_with_capacity_and_unit_cost(SRC_A, TGT_Y, 2, 2)  # weaker match
    smcf.add_arc_with_capacity_and_unit_cost(SRC_B, TGT_X, 2, 2)  # weaker match
    smcf.add_arc_with_capacity_and_unit_cost(SRC_B, TGT_Y, 2, 1)

    # null -> targets (capacity = demand, cost = 100)
    smcf.add_arc_with_capacity_and_unit_cost(NULL, TGT_X, 3, 100)
    smcf.add_arc_with_capacity_and_unit_cost(NULL, TGT_Y, 2, 100)

    # targets -> super_sink (capacity = demand, cost = 0)
    smcf.add_arc_with_capacity_and_unit_cost(TGT_X, SUPER_SINK, 3, 0)
    smcf.add_arc_with_capacity_and_unit_cost(TGT_Y, SUPER_SINK, 2, 0)

    # Set supply/demand
    smcf.set_node_supply(SUPER_SOURCE, total_demand)
    smcf.set_node_supply(SUPER_SINK, -total_demand)

    status = smcf.solve()

    node_names = {0: "SOURCE", 1: "SINK", 2: "NULL", 3: "A", 4: "B", 5: "X", 6: "Y"}

    if status == smcf.OPTIMAL:
        logger.info("OPTIMAL solution found (cost=%d)", smcf.optimal_cost())
        null_flow = 0
        for arc in range(smcf.num_arcs()):
            flow = smcf.flow(arc)
            if flow > 0:
                tail = node_names[smcf.tail(arc)]
                head = node_names[smcf.head(arc)]
                logger.info(
                    "  %s -> %s: flow=%d cost=%d",
                    tail, head, flow, smcf.unit_cost(arc),
                )
                if smcf.tail(arc) == NULL:
                    null_flow += flow

        logger.info("NULL flow (gap): %d / %d demand", null_flow, total_demand)

        # Verify: A->X=2, B->Y=2, NULL->X=1 (1 unit gap on X)
        assert smcf.optimal_cost() == 1 * 2 + 1 * 2 + 100 * 1  # = 104
        assert null_flow == 1
        logger.info("All assertions passed. OR-Tools is working correctly.")
    else:
        logger.error("Solver returned status %d (not optimal)", status)


if __name__ == "__main__":
    main()
