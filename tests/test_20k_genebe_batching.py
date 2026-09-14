from __future__ import annotations

from scripts.run_20k_gene_be_experiment import batch_plan, build_variants


def test_20k_plans_into_twenty_batches_of_1000():
    variants = build_variants(20_000)
    plan = batch_plan(len(variants), 1000)
    assert len(variants) == 20_000
    assert len(plan) == 20
    assert all((end - start) == 1000 for start, end in plan)
    assert plan[0] == (0, 1000)
    assert plan[-1] == (19_000, 20_000)


def test_batch_plan_handles_non_multiple():
    plan = batch_plan(20_001, 1000)
    assert len(plan) == 21
    assert plan[-1] == (20_000, 20_001)
