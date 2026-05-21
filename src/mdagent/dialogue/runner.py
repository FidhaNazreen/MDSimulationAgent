"""DialogueRunner — PTY-driven interactive process driver.

Drives an interactive CLI deterministically by:

  1. spawning the process under a PTY,
  2. reading output until the `PromptRecognizer` returns a Prompt,
  3. resolving the Prompt against the `DialoguePlan` (or `policy_default`,
     or asking the user in `interactive` mode),
  4. writing the answer back to the PTY,
  5. logging the exchange and looping.

Modes:
  - `normal`    : every prompt must be recognized AND resolvable, else raise.
  - `discovery` : unrecognized prompts are recorded (DialogueDiscovery) and
                  a default answer is sent (currently: empty line). Recognized
                  prompts that lack a plan answer fail as in normal mode.

Designed so that `pdb2gmx` is just the first user. Pass a different
`PromptRecognizer` (and the appropriate `argv`) to drive any other
interactive binary.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Callable, Iterator, Literal

import pexpect

from .plan import DialoguePlan, EmptyPlan
from .types import (
    DialogueDiscovery,
    DialogueResult,
    DialogueTimeoutError,
    Exchange,
    NonZeroExitError,
    Prompt,
    PromptRecognizer,
    UnexpectedPromptError,
)

PolicyDefault = Callable[[Prompt], tuple[str, str] | None]
"""Returns (answer, plan_field_descriptor) or None to escalate."""

InteractiveAsk = Callable[[Prompt], tuple[str, str]]
"""Asks the user; must always return (answer, plan_field_descriptor)."""

Mode = Literal["normal", "discovery"]


@dataclass
class DialogueDiagnostics:
    """Captured during a run for forensics: unknown-prompt discoveries, raw transcript."""

    discoveries: list[DialogueDiscovery] = field(default_factory=list)


class DialogueRunner:
    def __init__(
        self,
        recognizer: PromptRecognizer,
        *,
        env_overrides: dict[str, str] | None = None,
        read_timeout_s: float = 60.0,
        idle_after_answer_s: float = 0.1,
    ):
        self.recognizer = recognizer
        defaults = {"LC_ALL": "C", "LANG": "C", "TERM": "dumb"}
        if env_overrides:
            defaults.update(env_overrides)
        self.env_overrides = defaults
        self.read_timeout_s = read_timeout_s
        self.idle_after_answer_s = idle_after_answer_s

    def run(
        self,
        argv: list[str],
        *,
        cwd: str | os.PathLike[str],
        plan: DialoguePlan | None = None,
        policy_default: PolicyDefault | None = None,
        interactive_ask: InteractiveAsk | None = None,
        mode: Mode = "normal",
    ) -> tuple[DialogueResult, DialogueDiagnostics]:
        if plan is None:
            plan = EmptyPlan()
        env = os.environ.copy()
        env.update(self.env_overrides)

        child = pexpect.spawn(
            argv[0],
            args=argv[1:],
            cwd=str(cwd),
            env=env,
            timeout=self.read_timeout_s,
            encoding="utf-8",
            codec_errors="replace",
            echo=False,
        )

        exchanges: list[Exchange] = []
        diagnostics = DialogueDiagnostics()
        transcript_parts: list[str] = []
        buffer = ""
        last_recognized: Exchange | None = None
        t0 = time.monotonic()

        try:
            while True:
                # Read whatever is available since the last answer; stop when the
                # recognizer says the buffer ends in a prompt OR the child exits.
                try:
                    new_data = _read_until_recognizable_or_eof(
                        child, self.recognizer, buffer, self.read_timeout_s, plan, recognizer_state=None
                    )
                except pexpect.exceptions.TIMEOUT as e:
                    raise DialogueTimeoutError(
                        f"no recognized prompt within {self.read_timeout_s}s"
                    ) from e

                buffer += new_data
                transcript_parts.append(new_data)

                if not child.isalive() and not new_data:
                    # Child exited without any further output.
                    break

                prompt = self.recognizer.recognize(buffer)
                if prompt is None:
                    # If child exited and we have no more prompts, clean termination.
                    if not child.isalive():
                        break
                    # Otherwise we read something but no prompt matched — in normal mode
                    # this would be an UnexpectedPromptError, but only after we're sure
                    # the binary is actually waiting on stdin. Heuristic: if the child
                    # is alive and has produced trailing output that doesn't match,
                    # raise.
                    raise UnexpectedPromptError(
                        "buffer contains unrecognized trailing output",
                        raw_buffer_tail=buffer[-2000:],
                        last_recognized_exchange=last_recognized,
                        argv=argv,
                    )

                # Resolve the answer.
                resolution = plan.resolve(prompt)
                source = "plan"
                if resolution is None and policy_default is not None:
                    resolution = policy_default(prompt)
                    source = "policy_default" if resolution is not None else source
                if resolution is None and interactive_ask is not None:
                    resolution = interactive_ask(prompt)
                    source = "interactive_user"
                if resolution is None:
                    if mode == "discovery":
                        resolution = ("", "discovery_default")
                        source = "discovery"
                        diagnostics.discoveries.append(
                            DialogueDiscovery(raw_text=prompt.raw_text, buffer_at_capture=buffer[-2000:])
                        )
                    else:
                        raise UnexpectedPromptError(
                            f"plan has no answer for prompt kind={prompt.kind.value} context={prompt.context}",
                            raw_buffer_tail=buffer[-2000:],
                            last_recognized_exchange=last_recognized,
                            argv=argv,
                        )

                answer, plan_field = resolution
                exch = Exchange(prompt=prompt, answer=answer, answer_source=source, plan_field=plan_field)
                exchanges.append(exch)
                last_recognized = exch

                child.sendline(answer)
                # Clear the buffer of the prompt that just got answered: the prompt
                # text plus any echo. Cheap heuristic — re-anchor at length 0 after
                # sending an answer; the recognizer only ever needs trailing output.
                buffer = ""
                # Small idle to let the child process the answer.
                time.sleep(self.idle_after_answer_s)

            # Drain remainder.
            try:
                child.expect(pexpect.EOF, timeout=2.0)
                if child.before:
                    transcript_parts.append(child.before)
            except pexpect.exceptions.TIMEOUT:
                pass
            child.close()
            exit_status = child.exitstatus if child.exitstatus is not None else (child.signalstatus or 1)

        except UnexpectedPromptError:
            try:
                if child.isalive():
                    child.terminate(force=True)
            except Exception:
                pass
            raise

        wall = time.monotonic() - t0
        result = DialogueResult(
            argv=list(argv),
            exit_status=exit_status,
            wall_time_s=wall,
            exchanges=exchanges,
            raw_transcript="".join(transcript_parts),
        )

        if exit_status != 0:
            # The caller may or may not consider this a failure (recognizers can
            # be wrong about whether the binary should have exited 0). Raise by
            # default so unattended runs surface failure early.
            raise NonZeroExitError(
                f"{argv[0]} exited with status {exit_status}",
                exit_status=exit_status,
            )

        return result, diagnostics


def _read_until_recognizable_or_eof(
    child: pexpect.spawn,
    recognizer: PromptRecognizer,
    initial_buffer: str,
    timeout_s: float,
    plan: DialoguePlan,
    *,
    recognizer_state=None,
) -> str:
    """Read from the child until the recognizer would recognize a prompt or the child exits.

    Reads one chunk at a time (small timeout per read), accumulates, and checks
    the recognizer after each chunk. Returns the new data appended since the call.
    """
    deadline = time.monotonic() + timeout_s
    new_data_parts: list[str] = []
    accumulator = initial_buffer

    while True:
        # If the recognizer already sees a prompt in the existing buffer, we're done.
        if recognizer.recognize(accumulator) is not None:
            return "".join(new_data_parts)

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise pexpect.exceptions.TIMEOUT("read deadline exceeded")

        try:
            chunk = child.read_nonblocking(size=4096, timeout=min(0.2, remaining))
        except pexpect.exceptions.TIMEOUT:
            if not child.isalive():
                return "".join(new_data_parts)
            continue
        except pexpect.exceptions.EOF:
            if child.before:
                new_data_parts.append(child.before)
            return "".join(new_data_parts)

        if not chunk:
            if not child.isalive():
                return "".join(new_data_parts)
            continue

        new_data_parts.append(chunk)
        accumulator += chunk

        if recognizer.recognize(accumulator) is not None:
            return "".join(new_data_parts)
