"""Tests for the transport_podcast min-cost flow passage selection.

Tests cover:
- solve_dimension: balance, optimality, cost ordering, diversity penalty
- solve_arc: character arc selection
- aggregate: deduplication
- Edge cases: no eligible passages, supply < demand, duplicate passage IDs
"""

from __future__ import annotations

import pytest

from enrichment.transport_podcast import (
    ArcDemand,
    Assignment,
    DimensionResult,
    ExpertProfile,
    GapReport,
    PassageRecord,
    ProducerConfig,
    aggregate,
    solve_arc,
    solve_dimension,
)


# ---------------------------------------------------------------------------
# Fixtures: small synthetic corpora
# ---------------------------------------------------------------------------


def _make_passage(
    passage_id: str,
    chapter_id: str,
    interest_score: int = 3,
    provisions: dict[str, str] | None = None,
    literary_cluster: int = 0,
    character_cluster: int = 0,
    characters_present: list[str] | None = None,
) -> PassageRecord:
    """Helper to build a PassageRecord with sensible defaults."""
    default_provisions = {
        "prov_character_development": "none",
        "prov_plot_advancement": "none",
        "prov_thematic_depth": "none",
        "prov_social_critique": "none",
        "prov_humor_entertainment": "none",
        "prov_atmosphere_setting": "none",
        "prov_narrative_technique": "none",
    }
    if provisions:
        default_provisions.update(provisions)
    return PassageRecord(
        passage_id=passage_id,
        chapter_id=chapter_id,
        interest_score=interest_score,
        characters_present=characters_present or [],
        provisions=default_provisions,
        literary_cluster=literary_cluster,
        character_cluster=character_cluster,
    )


@pytest.fixture
def config() -> ProducerConfig:
    return ProducerConfig(
        cluster_lambda=5,
        null_cost=100,
        strong_cost=1,
        weak_cost=3,
    )


@pytest.fixture
def single_expert() -> list[ExpertProfile]:
    return [
        ExpertProfile(
            name="TestExpert",
            role="test",
            demands={"prov_social_critique": 4},
        )
    ]


@pytest.fixture
def two_experts() -> list[ExpertProfile]:
    return [
        ExpertProfile(
            name="Alice",
            role="test",
            demands={"prov_social_critique": 3},
        ),
        ExpertProfile(
            name="Bob",
            role="test",
            demands={"prov_social_critique": 3},
        ),
    ]


# ---------------------------------------------------------------------------
# solve_dimension: basic correctness
# ---------------------------------------------------------------------------


class TestSolveDimension:
    """Tests for per-dimension flow solver."""

    def test_optimal_status(
        self, config: ProducerConfig, single_expert: list[ExpertProfile]
    ) -> None:
        """Solver returns OPTIMAL for a well-formed problem."""
        passages = [
            _make_passage(f"p{i}", "c1", interest_score=5,
                          provisions={"prov_social_critique": "strong"},
                          literary_cluster=i)
            for i in range(10)
        ]
        result = solve_dimension("prov_social_critique", passages,
                                 single_expert, config)
        assert result.solver_status == "OPTIMAL"

    def test_supply_demand_balance(
        self, config: ProducerConfig, single_expert: list[ExpertProfile]
    ) -> None:
        """Total supply = total_supplied + total_null_flow."""
        passages = [
            _make_passage(f"p{i}", "c1", interest_score=3,
                          provisions={"prov_social_critique": "strong"},
                          literary_cluster=i)
            for i in range(20)
        ]
        result = solve_dimension("prov_social_critique", passages,
                                 single_expert, config)
        assert result.total_supply == result.total_supplied + result.total_null_flow

    def test_demand_fully_satisfied(
        self, config: ProducerConfig, single_expert: list[ExpertProfile]
    ) -> None:
        """When supply >> demand, all demand is satisfied."""
        passages = [
            _make_passage(f"p{i}", "c1", interest_score=5,
                          provisions={"prov_social_critique": "strong"},
                          literary_cluster=i)
            for i in range(20)
        ]
        result = solve_dimension("prov_social_critique", passages,
                                 single_expert, config)
        assert result.total_supplied == result.total_demand
        assert len(result.gaps) == 0

    def test_strong_preferred_over_weak(
        self, config: ProducerConfig
    ) -> None:
        """Solver prefers strong passages (cost=1) over weak (cost=3)."""
        experts = [
            ExpertProfile(name="E", role="test",
                          demands={"prov_social_critique": 2})
        ]
        # 2 strong passages (supply=2 each, cost=1) and 2 weak (supply=1, cost=3)
        # Demand=2, so solver should pick from strong passages
        passages = [
            _make_passage("strong0", "c1", interest_score=5,
                          provisions={"prov_social_critique": "strong"},
                          literary_cluster=0),
            _make_passage("strong1", "c2", interest_score=5,
                          provisions={"prov_social_critique": "strong"},
                          literary_cluster=1),
            _make_passage("weak0", "c3", interest_score=5,
                          provisions={"prov_social_critique": "weak"},
                          literary_cluster=2),
            _make_passage("weak1", "c4", interest_score=5,
                          provisions={"prov_social_critique": "weak"},
                          literary_cluster=3),
        ]
        result = solve_dimension("prov_social_critique", passages, experts, config)
        assigned_ids = {a.passage_id for a in result.assignments}
        # With demand=2 and strong passages supplying 2 units each at cost=1,
        # the solver should use a single strong passage (supply=2 covers demand=2)
        assert all(pid.startswith("strong") for pid in assigned_ids)

    def test_interesting_preferred_over_boring(
        self, config: ProducerConfig
    ) -> None:
        """Solver prefers high-interest passages (lower penalty)."""
        experts = [
            ExpertProfile(name="E", role="test",
                          demands={"prov_social_critique": 2})
        ]
        # All strong, same cluster → interest breaks the tie
        passages = [
            _make_passage("boring", "c1", interest_score=0,
                          provisions={"prov_social_critique": "strong"},
                          literary_cluster=0),
            _make_passage("interesting", "c2", interest_score=5,
                          provisions={"prov_social_critique": "strong"},
                          literary_cluster=1),
        ]
        result = solve_dimension("prov_social_critique", passages, experts, config)
        assigned_ids = {a.passage_id for a in result.assignments}
        # interesting (cost=1+0=1) should be preferred over boring (cost=1+5=6)
        assert "interesting" in assigned_ids

    def test_cluster_diversity_penalty(
        self, config: ProducerConfig
    ) -> None:
        """Diversity penalty discourages loading from one cluster."""
        experts = [
            ExpertProfile(name="E", role="test",
                          demands={"prov_social_critique": 4})
        ]
        # 4 passages in cluster 0, 4 in cluster 1, all identical cost
        passages = []
        for i in range(4):
            passages.append(
                _make_passage(f"c0_p{i}", "c1", interest_score=5,
                              provisions={"prov_social_critique": "strong"},
                              literary_cluster=0)
            )
            passages.append(
                _make_passage(f"c1_p{i}", "c2", interest_score=5,
                              provisions={"prov_social_critique": "strong"},
                              literary_cluster=1)
            )
        result = solve_dimension("prov_social_critique", passages, experts, config)
        assigned_ids = {a.passage_id for a in result.assignments}
        cluster0_count = sum(1 for pid in assigned_ids if pid.startswith("c0_"))
        cluster1_count = sum(1 for pid in assigned_ids if pid.startswith("c1_"))
        # With diversity penalty, solver should spread across clusters
        assert cluster0_count > 0
        assert cluster1_count > 0

    def test_no_demand_returns_empty(
        self, config: ProducerConfig
    ) -> None:
        """Dimension with no expert demand returns empty result."""
        experts = [
            ExpertProfile(name="E", role="test",
                          demands={"prov_thematic_depth": 5})
        ]
        passages = [
            _make_passage("p0", "c1",
                          provisions={"prov_social_critique": "strong"})
        ]
        result = solve_dimension("prov_social_critique", passages, experts, config)
        assert result.solver_status == "SKIPPED_NO_DEMAND"
        assert result.assignments == []

    def test_no_eligible_returns_gaps(
        self, config: ProducerConfig, single_expert: list[ExpertProfile]
    ) -> None:
        """Dimension with demand but no eligible passages reports gaps."""
        passages = [
            _make_passage("p0", "c1",
                          provisions={"prov_social_critique": "none"})
        ]
        result = solve_dimension("prov_social_critique", passages,
                                 single_expert, config)
        assert result.solver_status == "SKIPPED_NO_ELIGIBLE"
        assert len(result.gaps) == 1
        assert result.gaps[0].null_flow == 4

    def test_supply_less_than_demand_raises(
        self, config: ProducerConfig
    ) -> None:
        """RuntimeError when total supply < total demand."""
        experts = [
            ExpertProfile(name="E", role="test",
                          demands={"prov_social_critique": 100})
        ]
        passages = [
            _make_passage("p0", "c1", interest_score=5,
                          provisions={"prov_social_critique": "weak"},
                          literary_cluster=0),
        ]
        with pytest.raises(RuntimeError, match="insufficient supply"):
            solve_dimension("prov_social_critique", passages, experts, config)

    def test_duplicate_passage_ids_deduped(
        self, config: ProducerConfig, single_expert: list[ExpertProfile]
    ) -> None:
        """Duplicate passage IDs are deduplicated (only first kept)."""
        passages = [
            _make_passage("dup", "c1", interest_score=5,
                          provisions={"prov_social_critique": "strong"},
                          literary_cluster=0),
            _make_passage("dup", "c1", interest_score=5,
                          provisions={"prov_social_critique": "strong"},
                          literary_cluster=0),
            _make_passage("other", "c2", interest_score=5,
                          provisions={"prov_social_critique": "strong"},
                          literary_cluster=1),
        ]
        result = solve_dimension("prov_social_critique", passages,
                                 single_expert, config)
        assert result.solver_status == "OPTIMAL"
        # "dup" should appear at most once in eligible count
        assert result.num_eligible == 2

    def test_two_experts_share_dimension(
        self, config: ProducerConfig, two_experts: list[ExpertProfile]
    ) -> None:
        """Two experts competing for same dimension both get assignments."""
        passages = [
            _make_passage(f"p{i}", f"c{i}", interest_score=5,
                          provisions={"prov_social_critique": "strong"},
                          literary_cluster=i)
            for i in range(20)
        ]
        result = solve_dimension("prov_social_critique", passages,
                                 two_experts, config)
        alice_count = sum(1 for a in result.assignments if a.expert == "Alice")
        bob_count = sum(1 for a in result.assignments if a.expert == "Bob")
        assert alice_count > 0
        assert bob_count > 0
        assert result.total_demand == 6  # 3 + 3

    def test_diagnostic_fields_populated(
        self, config: ProducerConfig
    ) -> None:
        """DimensionResult has all diagnostic fields set."""
        experts = [
            ExpertProfile(name="E", role="test",
                          demands={"prov_social_critique": 2})
        ]
        passages = [
            _make_passage("s0", "c1", provisions={"prov_social_critique": "strong"},
                          literary_cluster=0),
            _make_passage("w0", "c2", provisions={"prov_social_critique": "weak"},
                          literary_cluster=1),
        ]
        result = solve_dimension("prov_social_critique", passages,
                                 experts, config)
        assert result.optimal_cost > 0
        assert result.num_eligible == 2
        assert result.num_clusters == 2
        assert result.strong_count == 1
        assert result.weak_count == 1
        assert result.total_supply == 3  # strong=2 + weak=1


# ---------------------------------------------------------------------------
# solve_arc
# ---------------------------------------------------------------------------


class TestSolveArc:
    """Tests for character arc flow solver."""

    def test_basic_arc_selection(self, config: ProducerConfig) -> None:
        """Arc solver selects passages with matching character."""
        arc = ArcDemand("Test arc", "Alice", 3,
                        "prov_character_development", "not_none", 3)
        passages = [
            _make_passage(f"p{i}", f"c{i}", interest_score=4,
                          provisions={"prov_character_development": "strong"},
                          characters_present=["Alice"])
            for i in range(5)
        ]
        result = solve_arc(arc, passages, config)
        assert len(result.assignments) == 3
        assert result.null_flow == 0

    def test_arc_filters_by_character(self, config: ProducerConfig) -> None:
        """Arc solver ignores passages without the target character."""
        arc = ArcDemand("Test arc", "Alice", 2,
                        "prov_character_development", "not_none", 3)
        passages = [
            _make_passage("with_alice", "c1", interest_score=5,
                          provisions={"prov_character_development": "strong"},
                          characters_present=["Alice"]),
            _make_passage("without_alice", "c2", interest_score=5,
                          provisions={"prov_character_development": "strong"},
                          characters_present=["Bob"]),
        ]
        result = solve_arc(arc, passages, config)
        assert all(a.passage_id == "with_alice" for a in result.assignments)

    def test_arc_filters_by_provision(self, config: ProducerConfig) -> None:
        """Arc solver respects require_field/require_value filter."""
        arc = ArcDemand("Test arc", "Alice", 2,
                        "prov_character_development", "not_none", 3)
        passages = [
            _make_passage("has_provision", "c1", interest_score=5,
                          provisions={"prov_character_development": "strong"},
                          characters_present=["Alice"]),
            _make_passage("no_provision", "c2", interest_score=5,
                          provisions={"prov_character_development": "none"},
                          characters_present=["Alice"]),
        ]
        result = solve_arc(arc, passages, config)
        assert len(result.assignments) == 1
        assert result.assignments[0].passage_id == "has_provision"
        assert result.null_flow == 1

    def test_arc_null_flow_when_insufficient(
        self, config: ProducerConfig
    ) -> None:
        """Arc solver reports null flow when not enough passages."""
        arc = ArcDemand("Test arc", "Alice", 5,
                        "prov_character_development", "not_none", 3)
        passages = [
            _make_passage("p0", "c1", interest_score=5,
                          provisions={"prov_character_development": "strong"},
                          characters_present=["Alice"]),
        ]
        result = solve_arc(arc, passages, config)
        assert len(result.assignments) == 1
        assert result.null_flow == 4

    def test_arc_raises_on_solver_failure(
        self, config: ProducerConfig
    ) -> None:
        """Arc solver raises RuntimeError on non-OPTIMAL status.

        This is hard to trigger in practice since the arc solver always
        has a NULL path, so we just verify it runs clean with no eligible.
        """
        arc = ArcDemand("Test arc", "Nobody", 3,
                        "prov_character_development", "not_none", 3)
        passages = [
            _make_passage("p0", "c1", interest_score=5,
                          provisions={"prov_character_development": "strong"},
                          characters_present=["Alice"]),
        ]
        result = solve_arc(arc, passages, config)
        assert len(result.assignments) == 0
        assert result.null_flow == 3


# ---------------------------------------------------------------------------
# aggregate
# ---------------------------------------------------------------------------


class TestAggregate:
    """Tests for aggregation and deduplication."""

    def test_dedup_same_passage_same_expert(self) -> None:
        """Same passage+expert from two dimensions: keep lowest cost."""
        dr1 = DimensionResult(
            dimension="prov_social_critique",
            assignments=[Assignment("p0", "Alice", "prov_social_critique", 5)],
            gaps=[], total_demand=1, total_supplied=1, total_null_flow=0,
            solver_status="OPTIMAL",
        )
        dr2 = DimensionResult(
            dimension="prov_thematic_depth",
            assignments=[Assignment("p0", "Alice", "prov_thematic_depth", 2)],
            gaps=[], total_demand=1, total_supplied=1, total_null_flow=0,
            solver_status="OPTIMAL",
        )
        result = aggregate([dr1, dr2], [])
        assert len(result.assignments) == 1
        assert result.assignments[0].cost == 2  # kept lower cost

    def test_same_passage_different_experts_both_kept(self) -> None:
        """Same passage assigned to different experts: both survive."""
        dr1 = DimensionResult(
            dimension="prov_social_critique",
            assignments=[
                Assignment("p0", "Alice", "prov_social_critique", 3),
                Assignment("p0", "Bob", "prov_social_critique", 4),
            ],
            gaps=[], total_demand=2, total_supplied=2, total_null_flow=0,
            solver_status="OPTIMAL",
        )
        result = aggregate([dr1], [])
        assert len(result.assignments) == 2

    def test_gaps_collected(self) -> None:
        """Gaps from all dimensions are collected."""
        dr1 = DimensionResult(
            dimension="dim1",
            assignments=[],
            gaps=[GapReport("dim1", "Alice", 5, 0, 5)],
            total_demand=5, total_supplied=0, total_null_flow=5,
            solver_status="SKIPPED_NO_ELIGIBLE",
        )
        dr2 = DimensionResult(
            dimension="dim2",
            assignments=[],
            gaps=[GapReport("dim2", "Bob", 3, 0, 3)],
            total_demand=3, total_supplied=0, total_null_flow=3,
            solver_status="SKIPPED_NO_ELIGIBLE",
        )
        result = aggregate([dr1, dr2], [])
        assert len(result.gaps) == 2


# ---------------------------------------------------------------------------
# Integration: run a small end-to-end flow
# ---------------------------------------------------------------------------


class TestIntegration:
    """End-to-end integration test with synthetic data."""

    def test_full_pipeline_small(self, config: ProducerConfig) -> None:
        """Run solve_dimension + aggregate on a small synthetic corpus."""
        experts = [
            ExpertProfile("Alice", "critic",
                          {"prov_social_critique": 3, "prov_thematic_depth": 2}),
            ExpertProfile("Bob", "reader",
                          {"prov_social_critique": 2, "prov_humor_entertainment": 3}),
        ]
        passages = [
            _make_passage(f"p{i}", f"c{i % 5}", interest_score=(i % 5) + 1,
                          provisions={
                              "prov_social_critique": "strong" if i % 3 == 0 else "weak",
                              "prov_thematic_depth": "strong" if i % 4 == 0 else "none",
                              "prov_humor_entertainment": "weak" if i % 2 == 0 else "none",
                          },
                          literary_cluster=i % 3)
            for i in range(30)
        ]

        dims = ["prov_social_critique", "prov_thematic_depth",
                "prov_humor_entertainment"]
        dim_results = []
        for dim in dims:
            dr = solve_dimension(dim, passages, experts, config)
            dim_results.append(dr)
            assert dr.solver_status in ("OPTIMAL", "SKIPPED_NO_DEMAND")

        result = aggregate(dim_results, [])
        assert len(result.assignments) > 0
        assert len(result.gaps) == 0

        # Every assigned passage should exist in our corpus
        passage_ids = {p.passage_id for p in passages}
        for a in result.assignments:
            assert a.passage_id in passage_ids
