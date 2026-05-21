"""Tiny mock interactive process for testing DialogueRunner.

Prints a sequence of "prompts" and reads stdin for answers. The sequence
is driven by a JSON scenario file passed via --scenario. This way each
test can exercise a different prompt pattern without compiling anything.

Scenario JSON shape:

    {
      "exit_status": 0,
      "steps": [
        {"prompt": "Select the Force Field:\n0: AMBER99SB\n1: OPLS-AA\nChoice: ",
         "validate_answer": ["0", "1"]},
        {"prompt": "Histidine HIS 15 chain A choice [0=HID,1=HIE,2=HIP]: ",
         "validate_answer": ["0", "1", "2"]},
        ...
      ]
    }

If `validate_answer` is present and the received answer isn't in the list,
the script exits non-zero (simulates a real binary rejecting bad input).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if "--scenario" not in sys.argv:
        sys.stderr.write("missing --scenario <path>\n")
        return 2
    scenario_path = sys.argv[sys.argv.index("--scenario") + 1]
    with open(scenario_path) as f:
        scenario = json.load(f)

    for step in scenario["steps"]:
        sys.stdout.write(step["prompt"])
        sys.stdout.flush()
        line = sys.stdin.readline()
        if not line:
            sys.stderr.write("stdin closed unexpectedly\n")
            return 3
        answer = line.rstrip("\n").rstrip("\r")
        accepted = step.get("validate_answer")
        if accepted is not None and answer not in accepted:
            sys.stderr.write(f"rejected answer: {answer!r} (expected one of {accepted})\n")
            return 4
        # Echo what we received so the runner sees output between prompts.
        sys.stdout.write(f"[mock] accepted: {answer}\n")
        sys.stdout.flush()

    sys.stdout.write("[mock] done\n")
    sys.stdout.flush()
    return scenario.get("exit_status", 0)


if __name__ == "__main__":
    sys.exit(main())
