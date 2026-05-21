"""Pdb2GmxPromptRecognizer unit tests against captured prompt strings.

These do not require GROMACS to be installed — the recognizer is pure regex.
The captured strings below were probed against `gmx pdb2gmx 2026.2-Homebrew`.
"""

from __future__ import annotations

from mdagent.dialogue import Pdb2GmxPromptRecognizer
from mdagent.dialogue.types import PromptKind


N_TERM_PROMPT = """Some prior output line.
Select start terminus type for LYS-1
 0: NH3+
 1: NH2
 2: ZWITTERION_NH3+
 3: None
"""

C_TERM_PROMPT = """Start terminus LYS-1: NH3+
Select end terminus type for LEU-129
 0: COO-
 1: ZWITTERION_COO- (only use with zwitterions containing exactly one residue)
 2: COOH
 3: None
"""

INTER_LYS_PROMPT = """Processing chain 1 'A' (1001 atoms, 129 residues)
Which LYSINE type do you want for residue 1
0. Not protonated (charge 0) (LYS)
1. Protonated (charge +1) (LYSH)

Type a number:"""

INTER_HIS_PROMPT = """Will use HISE for residue 15
Which HISTIDINE type do you want for residue 15
0. H on ND1 only (HISD)
1. H on NE2 only (HISE)
2. H on ND1 and NE2 (HISH)
3. Coupled to Heme (HIS1)

Type a number:"""


def test_recognizes_n_terminus():
    r = Pdb2GmxPromptRecognizer()
    p = r.recognize(N_TERM_PROMPT)
    assert p is not None
    assert p.kind == PromptKind.TER_N_CHOICE
    assert p.context == {"residue": "LYS", "resid": 1}
    assert p.options["0"] == "NH3+"
    assert p.options["3"] == "None"


def test_recognizes_c_terminus():
    r = Pdb2GmxPromptRecognizer()
    p = r.recognize(C_TERM_PROMPT)
    assert p is not None
    assert p.kind == PromptKind.TER_C_CHOICE
    assert p.context == {"residue": "LEU", "resid": 129}
    assert p.options["0"] == "COO-"
    assert "ZWITTERION_COO-" in p.options["1"]


def test_recognizes_inter_lysine():
    r = Pdb2GmxPromptRecognizer()
    p = r.recognize(INTER_LYS_PROMPT)
    assert p is not None
    assert p.kind == PromptKind.INTER_RESIDUE_CHOICE
    assert p.context == {"residue_type": "LYSINE", "resid": 1}
    assert p.options == {"0": "Not protonated (charge 0) (LYS)", "1": "Protonated (charge +1) (LYSH)"}


def test_recognizes_inter_histidine():
    r = Pdb2GmxPromptRecognizer()
    p = r.recognize(INTER_HIS_PROMPT)
    assert p is not None
    assert p.kind == PromptKind.INTER_RESIDUE_CHOICE
    assert p.context == {"residue_type": "HISTIDINE", "resid": 15}
    assert len(p.options) == 4
    assert p.options["1"] == "H on NE2 only (HISE)"


# `ASPARTIC ACID` and `GLUTAMIC ACID` are spelled with a space in pdb2gmx output.
INTER_ASP_PROMPT = """\
Which ASPARTIC ACID type do you want for residue 18
0. Not protonated (charge -1) (ASP)
1. Protonated (charge 0) (ASPH)

Type a number:"""

INTER_GLU_PROMPT = """\
Which GLUTAMIC ACID type do you want for residue 7
0. Not protonated (charge -1) (GLU)
1. Protonated (charge 0) (GLUH)

Type a number:"""


def test_recognizes_aspartic_acid():
    r = Pdb2GmxPromptRecognizer()
    p = r.recognize(INTER_ASP_PROMPT)
    assert p is not None
    assert p.kind == PromptKind.INTER_RESIDUE_CHOICE
    assert p.context == {"residue_type": "ASPARTIC ACID", "resid": 18}


def test_recognizes_glutamic_acid():
    r = Pdb2GmxPromptRecognizer()
    p = r.recognize(INTER_GLU_PROMPT)
    assert p is not None
    assert p.kind == PromptKind.INTER_RESIDUE_CHOICE
    assert p.context == {"residue_type": "GLUTAMIC ACID", "resid": 7}


SS_PROMPT = """\
  CYS127   SG981   0.197   1.072   1.721   1.313   2.799   2.622   2.934
Link CYS-6 SG-48 and CYS-127 SG-981 (y/n) ?"""


def test_recognizes_disulfide_yn():
    r = Pdb2GmxPromptRecognizer()
    p = r.recognize(SS_PROMPT)
    assert p is not None
    assert p.kind == PromptKind.SS_YN
    assert p.context == {"resid_a": 6, "atom_a": 48, "resid_b": 127, "atom_b": 981}
    assert "y" in p.options and "n" in p.options


def test_returns_none_for_unrelated_output():
    r = Pdb2GmxPromptRecognizer()
    assert r.recognize("Some prior log line about hydrogen bonding network\n") is None
    assert r.recognize("") is None
    assert r.recognize("Linking CYS-6 SG-48 and CYS-127 SG-981...\n") is None


def test_only_anchors_on_trailing_prompt():
    """Output after a complete prompt block (e.g. result echo) should hide the prompt."""
    r = Pdb2GmxPromptRecognizer()
    # Append a result line after the inter prompt — recognizer must not match.
    extended = INTER_LYS_PROMPT + "\nReceived answer\n"
    assert r.recognize(extended) is None
