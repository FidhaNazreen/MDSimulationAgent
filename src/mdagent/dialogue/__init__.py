"""mdagent.dialogue — PTY-driven deterministic CLI dialogue subsystem.

DialogueRunner drives interactive processes (initially `pdb2gmx`) deterministically.
It is binary-agnostic: a `PromptRecognizer` plugs in per-binary semantics
(prompt → PromptKind classification + option parsing).

Key types:

  - PromptKind   : enum of semantic prompt classes (SELECT_FF, HIS_CHOICE, ...)
  - Prompt       : a recognized prompt instance (kind + options + context)
  - Exchange     : Prompt + the answer sent + the source of that answer
  - DialogueResult : full record of one DialogueRunner.run() invocation
  - PromptRecognizer : Protocol — turns raw output into Prompts
  - DialoguePlan : maps PromptKind+context → answer
  - DialogueRunner : the PTY loop itself
"""

from .types import (
    DialogueDiscovery,
    DialogueResult,
    DialogueTimeoutError,
    Exchange,
    NonZeroExitError,
    Prompt,
    PromptKind,
    PromptMismatchError,
    PromptRecognizer,
    UnexpectedPromptError,
)
from .plan import DialoguePlan, StaticPlan, EmptyPlan
from .runner import DialogueRunner
from .pdb2gmx_recognizer import Pdb2GmxPromptRecognizer

__all__ = [
    "PromptKind",
    "Prompt",
    "Exchange",
    "DialogueResult",
    "DialogueDiscovery",
    "PromptRecognizer",
    "DialoguePlan",
    "StaticPlan",
    "EmptyPlan",
    "DialogueRunner",
    "Pdb2GmxPromptRecognizer",
    "UnexpectedPromptError",
    "PromptMismatchError",
    "DialogueTimeoutError",
    "NonZeroExitError",
]
