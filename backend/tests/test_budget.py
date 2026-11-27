"""Budget ledger invariants (T12 unit half).

The ledger must keep `consumed + reserved + remaining == budget` at all
times, refuse reservations without latching a hard stop when other agents
merely hold the capacity, and latch the hard stop once the budget is spent.
"""

from __future__ import annotations

from app.budget import BudgetLedger
from app.models import RunState
from app.store import RunStore


def make_ledger(budget: int = 10_000, reserve: int = 3_000) -> tuple[BudgetLedger, RunState]:
    store = RunStore()
    run = store.create("budget test", budget_tokens=budget, max_depth=2, max_concurrency=3)
    return BudgetLedger(run, reserve), run


def assert_invariant(ledger: BudgetLedger, budget: int) -> None:
    assert ledger.consumed + ledger.run.reserved_tokens + ledger.remaining == budget


def test_reservations_keep_the_invariant() -> None:
    ledger, run = make_ledger()
    assert ledger.reserve("a2") == 3_000
    assert ledger.reserve("a3") == 3_000
    assert ledger.reserve("a4") == 3_000
    assert_invariant(ledger, 10_000)
    assert ledger.remaining == 1_000

    ledger.charge("a2", 500)
    assert_invariant(ledger, 10_000)
    assert ledger.remaining == 1_000

    assert ledger.reserve("a5") == 1_000
    assert_invariant(ledger, 10_000)
    assert ledger.remaining == 0


def test_full_reservation_does_not_latch_hard_stop() -> None:
    ledger, run = make_ledger()
    for agent_id in ("a2", "a3", "a4"):
        ledger.reserve(agent_id)
    ledger.reserve("a5")
    assert ledger.remaining == 0
    refused = ledger.reserve("a6")
    assert refused is None
    assert run.budget_hard_stop is False
    assert ledger.exhausted is False


def test_spending_to_budget_latches_hard_stop() -> None:
    ledger, run = make_ledger(budget=5_000, reserve=3_000)
    ledger.reserve("a2")
    ledger.charge("a2", 4_800)
    assert run.tokens_used == 4_800
    assert run.budget_hard_stop is False
    ledger.charge("a2", 200)
    assert run.budget_hard_stop is True
    assert ledger.exhausted is True
    assert ledger.reserve("a3") is None


def test_release_refunds_only_the_unused_part() -> None:
    ledger, run = make_ledger()
    ledger.reserve("a2")
    ledger.charge("a2", 1_200)
    refunded = ledger.release("a2")
    assert refunded == 1_800
    assert run.reserved_tokens == 0
    assert run.reservations == {}
    assert_invariant(ledger, 10_000)