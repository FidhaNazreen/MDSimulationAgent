"""Types for the dialogue subsystem.

A PromptKind enumerates the semantic classes of interactive prompts we
recognize across supported binaries. A Prompt is an instance of one — raw
text plus a parsed option table plus optional context (e.g. residue id).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class PromptKind(str, Enum):
    SELECT_FF = "select_ff"
    SELECT_WATER = "select_water"
    TER_N_CHOICE = "ter_n_choice"
    TER_C_CHOICE = "ter_c_choice"
    HIS_CHOICE = "his_choice"
    SS_YN = "ss_yn"
    INTER_RESIDUE_CHOICE = "inter_residue_choice"
    YN_GENERIC = "yn_generic"


@dataclass
class Prompt:
    """One recognized prompt.

    `options` maps a literal answer-string (typically a number "0", "1", ...
    or "y"/"n") to a human-readable label. `context` carries any parsed
    metadata — for an HIS prompt that's typically `{"resid": 15, "chain": "A"}`.
    """

    kind: PromptKind
    raw_text: str
    options: dict[str, str] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "raw_text": self.raw_text,
            "options": dict(self.options),
            "context": dict(self.context),
        }


@dataclass
class Exchange:
    """One prompt → answer pair, plus where the answer came from."""

    prompt: Prompt
    answer: str
    answer_source: str  # "plan" | "policy_default" | "interactive_user" | "discovery"
    plan_field: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt.to_dict(),
            "answer": self.answer,
            "answer_source": self.answer_source,
            "plan_field": self.plan_field,
        }


@dataclass
class DialogueResult:
    """Full record of a single DialogueRunner.run() invocation."""

    argv: list[str]
    exit_status: int
    wall_time_s: float
    exchanges: list[Exchange] = field(default_factory=list)
    raw_transcript: str = ""

    @property
    def ok(self) -> bool:
        return self.exit_status == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "argv": list(self.argv),
            "exit_status": self.exit_status,
            "wall_time_s": self.wall_time_s,
            "exchanges": [e.to_dict() for e in self.exchanges],
            "raw_transcript": self.raw_transcript,
        }


@dataclass
class DialogueDiscovery:
    """Captures unknown prompts encountered in discovery mode (no recognizer match)."""

    raw_text: str
    buffer_at_capture: str

    def to_dict(self) -> dict[str, Any]:
        return {"raw_text": self.raw_text, "buffer_at_capture": self.buffer_at_capture}


# ---- Errors -------------------------------------------------------------


class UnexpectedPromptError(RuntimeError):
    """The recognizer matched no PromptKind for the buffered output.

    Debug payload includes the raw buffer tail and the last recognized exchange
    (caller fills it in) so the user can see where prompt drift started.
    """

    def __init__(
        self,
        message: str,
        *,
        raw_buffer_tail: str = "",
        last_recognized_exchange: Exchange | None = None,
        argv: list[str] | None = None,
    ):
        super().__init__(message)
        self.raw_buffer_tail = raw_buffer_tail
        self.last_recognized_exchange = last_recognized_exchange
        self.argv = argv

    def debug_payload(self) -> dict[str, Any]:
        return {
            "message": str(self),
            "argv": self.argv,
            "raw_buffer_tail": self.raw_buffer_tail,
            "last_recognized_exchange": (
                self.last_recognized_exchange.to_dict()
                if self.last_recognized_exchange is not None
                else None
            ),
        }


class PromptMismatchError(RuntimeError):
    """A prompt was recognized but the plan has no answer for it.

    Distinct from `UnexpectedPromptError` (we recognized the kind but not the
    specific context the plan covers — e.g. the plan answered for HIS resid 12
    but the binary asked about resid 47).
    """


class DialogueTimeoutError(TimeoutError):
    """No recognizable prompt arrived within the timeout."""


class NonZeroExitError(RuntimeError):
    """Process exited non-zero before the dialogue completed."""

    def __init__(self, message: str, *, exit_status: int):
        super().__init__(message)
        self.exit_status = exit_status


# ---- Recognizer protocol -----------------------------------------------


class PromptRecognizer(Protocol):
    """Turn raw output bytes/text into Prompt instances.

    `binary` is the executable name this recognizer targets (e.g. 'pdb2gmx').
    `version` is a pinned-version identifier; the runner records it.

    `recognize(buffer)` returns either a Prompt (the trailing portion of the
    buffer matches a known prompt and is "ready for an answer") or None
    (no recognizable prompt yet — keep reading).
    """

    binary: str
    version: str

    def recognize(self, buffer: str) -> Prompt | None: ...
