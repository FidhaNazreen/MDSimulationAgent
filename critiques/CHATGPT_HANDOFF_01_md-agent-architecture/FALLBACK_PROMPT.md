# Fallback prompt: from-scratch redesign by codex / gpt-5

Use this prompt only if the iterative critique loop hits its round cap with `VERDICT: ISSUES_REMAIN` and the unresolved issues are substantive — i.e. the loop converged on something the user doesn't believe is right. Sending this is the "clean slate" branch: instead of asking GPT to critique an existing design, we ask it to propose one of its own with full visibility into the loop's accumulated context.

## How to send

```bash
SESSION_DIR=/Users/manu_jay/git_repos/MDSimulationAgent/critiques/CHATGPT_HANDOFF_01_md-agent-architecture

# Concatenate the full loop transcript + this fallback prompt into one stdin payload.
cat \
  "$SESSION_DIR"/R*_to_gpt.md \
  "$SESSION_DIR"/R*_from_gpt.md \
  "$SESSION_DIR"/FALLBACK_PROMPT.md \
  | codex exec -m gpt-5 \
      --output-last-message "$SESSION_DIR/FALLBACK_response.md" - \
      > "$SESSION_DIR/.codex_log_FALLBACK.txt" 2>&1
```

(The `R*` glob picks up every round of the prior loop in order so the gpt-5 model has the full history of what was tried, what was accepted, what was defended. The trailing `-` argument tells `codex exec` to read the prompt from stdin.)

If you want the model to start *truly* from a clean slate (ignoring the prior loop), drop the `R*_to_gpt.md` and `R*_from_gpt.md` from the cat. Default is to include them — usually you want the model to know what was already tried.

## The prompt to send (everything below this line)

---

You are being asked to redesign an agentic system from scratch. A prior critique loop with you (or another reviewer) ran for several rounds against an existing proposal but did not converge to something the user is confident in. The full transcript of that loop is attached above as `R*_to_gpt.md` (Claude's handoffs) and `R*_from_gpt.md` (your prior critiques and counterreplies). Use that context to learn what was tried and why it fell short — then propose your own architecture rather than incrementally patching the existing one.

### What we are building

An **agentic system for molecular dynamics (MD) simulation** that a user invokes by natural-language prompt. The system internally dispatches specialized sub-agents to do the multi-step work. The end deliverable is a set of **Claude skills** so a user can say "set up lysozyme in water for simulation" and have the skill layer pick the right sub-agents.

### Pinned scope (do not change these — design within them)

- **MD engine: GROMACS.** Chosen because the canonical lysozyme tutorial (PDB 1AKI) gives a reference oracle.
- **Compute: local-first** (Mac), **but design must be compute-agnostic**. Cloud / HPC support gets added later via an executor abstraction; v0 ships local-only but cannot paint itself into a corner.
- **Delivery: Claude skills.** Each user-meaningful step is its own skill; the orchestrator skill picks which to call.
- **v0 scope: structure-prep + topology + solvation/neutralization only.** No minimization, no dynamics, no analysis yet. Goal of v0 is to validate orchestration and skill boundaries on a non-trivial-but-bounded slice before paying for long runs.
- **Visualization required.** Traditional MD viewers (VMD primary; PyMOL or NGLview fallbacks). Must ask the user upfront, exactly once per workflow, whether viz is wanted and at which checkpoints. Must not break headless / unattended runs.

### What we want from you

Produce a complete v0 architecture. Be opinionated. Specifically:

1. **Agent roster.** Name each agent, its inputs/outputs, its responsibilities, its known failure modes. Explain why this decomposition is right for an agentic system (i.e. where decisions live and who owns them).
2. **Skill boundary map.** Which agents become which Claude skills. Which decisions surface to the user vs. stay internal with defaults.
3. **State and handoff model.** How agents pass artifacts between each other. Filesystem layout. How a run is resumable after a crash.
4. **Compute abstraction.** Concrete interface that supports local subprocess in v0 and remote execution (SLURM / cloud GPU) without re-architecting agents.
5. **QC strategy.** What gets checked when, what fails hard vs. soft, where the thresholds come from. Be specific — `|q| < some_eps` is not specific enough on its own; justify the epsilon.
6. **Visualization agent design.** Up-front ask, viewer selection, fallback when no viewer is installed, headless rendering, where output lives, how it's referenced from the report.
7. **Report agent contract.** What goes in the final report; how it cites the manifest; what guarantees we make about provenance and reproducibility.
8. **Explicit list of decision points** where the agent must ask the user vs. apply a default vs. refuse. With justification for each placement.
9. **What you would defer past v0** with a one-line reason each.
10. **What you think the *prior* loop got wrong** — based on the attached transcript, where do you think the previous design or its critiques went off-track? This is asked so you don't silently make the same mistake.

### Output format

Write the design as a single self-contained markdown document. Lead with a one-paragraph executive summary so the user can see the shape of the proposal in 30 seconds. Then the sections above, numbered 1–10. Then a final section titled **Open questions for the user** with the ≤5 questions you would most want answered before implementation begins.

Do not include a VERDICT line — this is a redesign, not a critique. Length is whatever it needs to be; quality over brevity, but no padding.
