"""DialoguePlan — maps a recognized Prompt to an answer.

Plans are how the orchestrator pre-records decisions (e.g. from
topology_plan.json) so the dialogue runs deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .types import Prompt, PromptKind


class DialoguePlan(Protocol):
    """Resolve `prompt` to a (answer, plan_field_path) pair.

    Return None if the plan has no answer — the runner will then consult
    `policy_default`, then prompt the user in interactive mode, or fail.
    """

    def resolve(self, prompt: Prompt) -> tuple[str, str] | None: ...


@dataclass
class StaticPlan:
    """Simple plan: a dict keyed by `(PromptKind, freeze(context))` or just `PromptKind`.

    Two-level lookup: try (kind, context_key) first, then fall back to just kind.
    `context_key` is built by serializing a configurable subset of the prompt's
    context dict (e.g. ('resid', 'chain') for HIS prompts).
    """

    by_kind_and_context: dict[tuple[PromptKind, tuple[tuple[str, Any], ...]], tuple[str, str]] = field(
        default_factory=dict
    )
    by_kind: dict[PromptKind, tuple[str, str]] = field(default_factory=dict)
    context_keys_per_kind: dict[PromptKind, tuple[str, ...]] = field(default_factory=dict)

    def resolve(self, prompt: Prompt) -> tuple[str, str] | None:
        ctx_keys = self.context_keys_per_kind.get(prompt.kind, ())
        if ctx_keys:
            ctx_tuple = tuple((k, prompt.context.get(k)) for k in ctx_keys)
            key = (prompt.kind, ctx_tuple)
            if key in self.by_kind_and_context:
                return self.by_kind_and_context[key]
        if prompt.kind in self.by_kind:
            return self.by_kind[prompt.kind]
        return None

    def add_answer(
        self,
        kind: PromptKind,
        answer: str,
        *,
        plan_field: str,
        context: dict[str, Any] | None = None,
        context_keys: tuple[str, ...] = (),
    ) -> None:
        if context is None or not context_keys:
            self.by_kind[kind] = (answer, plan_field)
            return
        self.context_keys_per_kind[kind] = context_keys
        ctx_tuple = tuple((k, context.get(k)) for k in context_keys)
        self.by_kind_and_context[(kind, ctx_tuple)] = (answer, plan_field)


class EmptyPlan:
    """A plan that resolves nothing. Useful for discovery-mode runs."""

    def resolve(self, prompt: Prompt) -> tuple[str, str] | None:
        return None
