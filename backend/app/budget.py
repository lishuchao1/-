"""Token budget ledger with reservations.

Invariant at every moment for consumed <= budget:
    consumed + reserved + remaining == budget

Spawn reserves a bucket; per-step usage draws the bucket down and any extra
goes straight to consumed; settling releases whatever is left.
"""

from __future__ import annotations

from .models import RunState


class BudgetLedger:
    def __init__(self, run: RunState, reserve_tokens: int, soft_ratio: float = 0.9):
        self.run = run
        self.reserve_tokens = max(1, reserve_tokens)
        self.soft_ratio = soft_ratio

    @property
    def consumed(self) -> int:
        return self.run.tokens_used

    @property
    def remaining(self) -> int:
        return max(0, self.run.budget_tokens - self.run.tokens_used - self.run.reserved_tokens)

    @property
    def exhausted(self) -> bool:
        return self.run.budget_hard_stop or self.consumed >= self.run.budget_tokens

    def reserve(self, agent_id: str) -> int | None:
        """Reserve a bucket for a new agent, or return None when no capacity is left.

        A reservation only fails hard when tokens have actually been consumed up
        to the budget; if other agents merely hold the remaining capacity, the
        caller gets None without latching the hard stop.
        """
        if self.consumed >= self.run.budget_tokens:
            self.run.budget_hard_stop = True
            return None
        if self.remaining <= 0:
            return None
        amount = min(self.reserve_tokens, self.remaining)
        self.run.reservations[agent_id] = amount
        self.run.reserved_tokens += amount
        return amount

    def charge(self, agent_id: str, tokens: int) -> int:
        """Charge usage for one step. Returns tokens drawn from the reservation."""
        if tokens <= 0:
            return 0
        held = self.run.reservations.get(agent_id, 0)
        draw = min(held, tokens)
        if draw:
            left = held - draw
            if left:
                self.run.reservations[agent_id] = left
            else:
                self.run.reservations.pop(agent_id, None)
            self.run.reserved_tokens -= draw
        self.run.tokens_used += tokens
        if self.run.tokens_used >= self.run.budget_tokens:
            self.run.budget_hard_stop = True
        return draw

    def release(self, agent_id: str) -> int:
        """Release the unused part of a reservation and return the refund."""
        held = self.run.reservations.pop(agent_id, 0)
        if held:
            self.run.reserved_tokens -= held
        return held

    def soft_limit_reached(self) -> bool:
        return self.run.tokens_used >= self.run.budget_tokens * self.soft_ratio