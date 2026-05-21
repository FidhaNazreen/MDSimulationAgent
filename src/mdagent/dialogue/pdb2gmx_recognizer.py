"""Pdb2GmxPromptRecognizer — semantic recognition of `gmx pdb2gmx` prompts.

Probed against GROMACS 2026.2 (Homebrew bottle). Prompt shapes recorded inline
in the regex patterns. Catalog probe (later) will regenerate this for other
pinned GROMACS versions.

Two prompt families are recognized:

  1. TER_N_CHOICE / TER_C_CHOICE — termini selection emitted with `-ter`:

         Select start terminus type for LYS-1
          0: NH3+
          1: NH2
          ...

     The recognized buffer ends after the numbered options. The reply is a
     single integer line. We rely on the option block ending without a
     trailing colon (pdb2gmx then reads stdin immediately).

  2. INTER_RESIDUE_CHOICE — residue-protonation selection emitted with `-inter`
     (or specific `-lys`/`-asp`/`-glu`/`-gln`/`-his`/`-cys` flags):

         Which LYSINE type do you want for residue 1
         0. Not protonated (charge 0) (LYS)
         1. Protonated (charge +1) (LYSH)

         Type a number:

     The literal "Type a number:" line is the distinctive sentinel — that's
     what we anchor on. Context carries `residue_type` (LYSINE, ASPARTATE,
     GLUTAMATE, GLUTAMINE, HISTIDINE, CYSTEINE) and `resid` (int).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .types import Prompt, PromptKind


_TER_RE = re.compile(
    r"Select\s+(?P<which>start|end)\s+terminus\s+type\s+for\s+(?P<res>\S+?)-(?P<num>\d+)\s*\n"
    r"(?P<options>(?:\s*\d+:.*\n)+)\s*\Z",
    re.MULTILINE,
)

_INTER_RE = re.compile(
    r"Which\s+(?P<restype>LYSINE|ARGININE|ASPARTATE|GLUTAMATE|GLUTAMINE|HISTIDINE|CYSTEINE)"
    r"\s+type\s+do\s+you\s+want\s+for\s+residue\s+(?P<resid>\d+)\s*\n"
    r"(?P<options>(?:\d+\.\s.*\n)+)"
    r"\s*\n?Type\s+a\s+number:\s*\Z",
    re.MULTILINE,
)

_OPTION_LINE_TER = re.compile(r"^\s*(?P<key>\d+):\s+(?P<label>.+?)\s*$", re.MULTILINE)
_OPTION_LINE_INTER = re.compile(r"^\s*(?P<key>\d+)\.\s+(?P<label>.+?)\s*$", re.MULTILINE)


@dataclass
class Pdb2GmxPromptRecognizer:
    binary: str = "gmx pdb2gmx"
    version: str = "2026.2"

    def recognize(self, buffer: str) -> Prompt | None:
        # `\Z` in each pattern anchors the match to end-of-buffer, so we
        # only fire when the prompt is the most recent thing emitted —
        # no need for a separate trailing check.
        m = _INTER_RE.search(buffer)
        if m:
            return self._inter_prompt(m, buffer[-1500:])
        m = _TER_RE.search(buffer)
        if m:
            return self._ter_prompt(m, buffer[-1500:])
        return None

    @staticmethod
    def _ter_prompt(m: re.Match[str], tail: str) -> Prompt:
        which = m.group("which")
        kind = PromptKind.TER_N_CHOICE if which == "start" else PromptKind.TER_C_CHOICE
        opts = {
            o.group("key"): o.group("label").rstrip()
            for o in _OPTION_LINE_TER.finditer(m.group("options"))
        }
        return Prompt(
            kind=kind,
            raw_text=tail,
            options=opts,
            context={"residue": m.group("res"), "resid": int(m.group("num"))},
        )

    @staticmethod
    def _inter_prompt(m: re.Match[str], tail: str) -> Prompt:
        opts = {
            o.group("key"): o.group("label").rstrip()
            for o in _OPTION_LINE_INTER.finditer(m.group("options"))
        }
        return Prompt(
            kind=PromptKind.INTER_RESIDUE_CHOICE,
            raw_text=tail,
            options=opts,
            context={
                "residue_type": m.group("restype"),
                "resid": int(m.group("resid")),
            },
        )
