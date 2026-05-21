---
name: gpt-critique-loop
description: Run an iterative adversarial critique loop where GPT (via the local Codex CLI) acts as a sounding board on a plan, derivation, debug hypothesis, or other artifact Claude just produced. Claude writes a self-contained handoff with full context, asks GPT to find every hole, processes GPT's response, writes a counterreply (accepting/defending/clarifying point by point), and sends it back. Loop until GPT replies VERDICT APPROVED or a round cap (default 5) is hit, then auto-revise the original artifact to incorporate accepted feedback. Triggers include "have GPT review this plan", "ChatGPT handoff", "GPT sounding board", "find holes in this plan with GPT", "be critical with GPT", "critique loop", "second opinion from GPT", "adversarial review", or any phrasing where the user wants iterative back-and-forth criticism with GPT/ChatGPT/Codex on something Claude just produced — even when the user does not say "skill" or "loop". Especially valuable for plans involving non-trivial math, derivations, or architectural decisions where GPT's gap-finding is the point. All handoff, reply, counterreply, status, and final-revision files are written to disk round-by-round so the user can monitor in real time.
---

# GPT Critique Loop

Orchestrate an adversarial review loop with GPT (via the local Codex CLI) until convergence. GPT's job is to find holes; Claude's job is to either fix or defend, point by point. Every exchange lands on disk as a numbered file so the user can watch the conversation evolve.

## When to use this

The user wants GPT to critically review a plan or piece of work Claude just produced and then iterate to close gaps. Common phrasings: "have GPT review this", "ChatGPT handoff", "sounding-board this with GPT", "find holes in this plan", "be critical with GPT", "critique loop", "adversarial review".

If the user just wants a single one-shot GPT opinion (no loop), prefer `codex:rescue` directly — this skill is specifically for the iterative version with verdict-driven exit.

## Why this works

GPT and Claude have different blind spots. GPT (especially via Codex) is unusually good at spotting algebra slips, missing edge cases, and unstated assumptions in plans. Claude is good at integration with the codebase and producing concrete fixes. The loop alternates: GPT critiques, Claude responds, until GPT runs out of substantive objections. The user gets a hardened plan plus a complete record of which objections were accepted vs. defended and why.

The loop can fail two ways: Claude capitulates to every challenge (loop is wasted, plan becomes whatever GPT's last sentence said), or Claude defends every challenge (loop is wasted, GPT gives up and verdicts APPROVED to escape). Honest engagement round-by-round is the only mode that produces real value.

## Setup (before round 1)

1. **Identify the artifact.** What is GPT reviewing? Possibilities:
   - A plan in `tasks/todo.md`, a planning doc, or a `docs/` markdown file
   - Code Claude just wrote (point at a specific commit, diff, or set of files)
   - A derivation written out in a doc or in conversation
   - A debug hypothesis with proposed next steps

   If the artifact location isn't obvious from recent conversation, ask the user in one focused question. Record the artifact's path — the auto-revise step writes back here.

2. **Pick a topic slug.** Short kebab-case identifier reflecting the substance, used in filenames. Examples: `ruggiero-realignment`, `picard-r2`, `auth-jwt-rewrite`. Avoid `review-1`, `gpt-check`, etc. — they don't help future-you grep.

3. **Find the next handoff number.** Scan the chosen output dir (default `docs/`) for existing `CHATGPT_HANDOFF_<N>_*` files and directories. Take the max `N` and add 1. If none exist, start at 1. This keeps new sessions sequential with any historical record.

4. **Pick the round cap.** Default 5. Honor a different number if the user specified one. Below 3 usually isn't worth a loop; above 8 usually means the artifact is too big or the topic too vague.

5. **Create the session directory:**
   ```
   <output_dir>/CHATGPT_HANDOFF_<NN>_<topic>/
   ```
   And write `STATUS.md` inside:
   ```markdown
   # Critique Session <NN> — <topic>

   - Started: <ISO timestamp>
   - Round cap: <N>
   - Current round: 0
   - Latest verdict: (none)
   - Codex session ID: (set after round 1)
   - Original artifact: <abs path>
   - Output dir: <abs path>
   - Status: in_progress
   ```

6. **Tell the user once, in one line**, where the session lives and the cap. Example:
   > Critique session 20 (`ruggiero-realignment`) starting in `docs/CHATGPT_HANDOFF_20_ruggiero-realignment/`. Cap: 5 rounds.

## Round 1: build the handoff

Write `R1_to_gpt.md` in the session dir with three sections in this order.

### Section 1: Context bundle

GPT only gets one shot per round — no clarifying follow-ups. So unanswered questions silently become assumed gaps in GPT's review. Front-load context generously:

- The goal (what problem the plan/work addresses, what success looks like)
- Key prior decisions and **why** they were made — not just what was decided. GPT can't know which alternatives were already ruled out unless you say so.
- Relevant file paths with the specific functions or sections to look at. Quote short snippets inline for any code GPT needs to evaluate.
- Math or algebra written out **in full**. Don't make GPT chase definitions across files; restate symbols, units, and assumed identities locally.
- Constraints, prior failures, dead ends already explored, things that look promising but were ruled out.

Ten minutes spent on this section saves three wasted rounds of GPT asking about things that were already decided.

### Section 2: The artifact under review

The actual content being critiqued. If it's a plan, paste the full plan. If it's code, include the relevant excerpt or diff. If it's a derivation, write it out step by step with all symbols defined.

### Section 3: Critique prompt

Append this verbatim — do not paraphrase, the verdict format is parsed by Claude later:

```
You are an adversarial reviewer. Be critical. Be argumentative.
Find every hole: missing steps, wrong algebra, untested assumptions,
edge cases not addressed, implicit dependencies, claims without
evidence, off-by-one errors, sign errors, dimensional errors. Don't
be polite — if something is wrong, say so. Concision over hedging.

For each issue, state:
  - WHAT is wrong (specific, not vague — name the line or symbol)
  - WHY it matters (what breaks downstream if uncorrected)
  - WHAT to do (concrete fix, or what evidence would close the gap)

Number your issues. After all issues, end your response with exactly
one of these lines, no other text after it:

  VERDICT: APPROVED
  VERDICT: ISSUES_REMAIN

Use APPROVED only when there are no issues you would block on.
Minor nitpicks alone do not justify ISSUES_REMAIN — call them out
but still verdict APPROVED. Use ISSUES_REMAIN whenever any of your
issues are genuinely blocking.
```

Save the file. Print one line: `Round 1: handoff written → <path>`.

## Send a round to GPT (persistent codex session across rounds)

The skill uses a single persistent codex session that carries through every round. GPT therefore remembers its own prior wording, your counterreplies, and the whole thread verbatim — no paraphrase drift. Round 1 *starts* the session; rounds 2+ *resume* it by session ID.

### Round 1: start the session

```bash
codex exec --output-last-message <abs-path>/R1_from_gpt.md - \
  < <abs-path>/R1_to_gpt.md \
  > <abs-path>/.codex_log_R1.txt 2>&1
```

Then capture the session UUID from the log:

```bash
SESSION_ID=$(grep -oE 'session id: [0-9a-f-]+' <abs-path>/.codex_log_R1.txt | head -1 | sed 's/session id: //')
echo "$SESSION_ID" > <abs-path>/.codex_session_id
```

Write the session ID into `STATUS.md` (`Codex session ID: <UUID>`) so the user can see it and so recovery is possible if the loop is interrupted.

### Rounds 2+: resume the session

```bash
SESSION_ID=$(cat <abs-path>/.codex_session_id)
codex exec resume "$SESSION_ID" --output-last-message <abs-path>/R{N}_from_gpt.md - \
  < <abs-path>/R{N}_to_gpt.md \
  > <abs-path>/.codex_log_R{N}.txt 2>&1
```

Because the session is resumed, the counterreply file does **not** need to restate the full thread — GPT already has it. The counterreply is purely the new content (acknowledgments + updated artifact + continued critique prompt). Restating issues briefly by short identifier (e.g. "Re your point 3 about `bool` subclasses:") is still useful for *human* monitoring of the file, but is no longer necessary for GPT's understanding.

### Trailing `-` and stdin

The trailing `-` argument tells `codex exec` (and `codex exec resume`) to read the prompt from stdin, which we redirect from the round's `_to_gpt.md` file. This keeps the prompt as a normal file on disk (the user can read/edit it before sending if they want to step in).

### Reasoning effort: keep the default (`xhigh`). Do not lower it.

Codex's default reasoning effort for this user is `xhigh` and that is the point of using this skill — gap-finding is what `xhigh` is best at, and lowering it produces shallower critiques that miss exactly the holes the loop is meant to catch. If you find yourself tempted to add `-c 'reasoning_effort="medium"'` to make rounds faster, don't. The latency is the cost of the value. Each round at `xhigh` typically takes 1–4 minutes.

Use a generous Bash timeout (`timeout: 600000` = 10 min) so a thorough round doesn't get killed mid-thought.

If the user wants to pin a specific model, add `-m <model>` (e.g. `-m gpt-5.5`) on round 1 *and* round 2+ resume calls; without it, codex uses the configured default. As of CLI 0.129+, the default is `gpt-5.5`. If codex errors with "model requires a newer version of Codex", run `npm install -g @openai/codex@latest` and retry once.

### Transport failure handling and resume fallback

After each codex call, treat any of these as a transport failure:
- non-zero exit
- response file does not exist
- response file is empty or under ~50 bytes
- response file lacks any line starting with `VERDICT:`

**On round 1 failure**: retry once with the same command. If retry fails, abort the loop, write the error to STATUS.md, tell the user.

**On round 2+ failure**: first retry the *resume* command once. If that still fails (e.g. codex's session storage was cleaned up, session ID went stale, codex was reinstalled), fall back to a fresh session with the full transcript concatenated:

```bash
# Fallback: build a synthetic R{N}_to_gpt_FULL.md containing
# R1_to_gpt + R1_from_gpt + R2_to_gpt + R2_from_gpt + ... + R{N}_to_gpt,
# then send via fresh `codex exec` (no resume) and capture a NEW session id.
```

Write a one-line note in STATUS.md when this fallback triggers (`Round N: codex resume failed, switched to transcript-concat mode; new session id: <UUID>`) so the user knows the context model changed.

After codex returns successfully:

1. Read `R{N}_from_gpt.md`.
2. Parse the verdict: scan from the bottom for the first line matching `^VERDICT: (APPROVED|ISSUES_REMAIN)$`. If neither is found, treat as `ISSUES_REMAIN` and flag this in the status update.
3. Estimate issue count: count numbered top-level items (`1.`, `2.`, …) or top-level bullets in the body. Approximate is fine.
4. Update `STATUS.md` (current round, latest verdict, issue count).
5. Print a status block to the user — short, scannable, no fluff:
   ```
   Round <N> complete · Verdict: <APPROVED|ISSUES_REMAIN> · ~<K> issues
   Top issues:
     1. <one-line gist of issue 1>
     2. <one-line gist of issue 2>
     3. <one-line gist of issue 3>
   File: <path to R{N}_from_gpt.md>
   ```
   Include up to 3 issue gists. The user reads the file for full detail.

## Loop control

After each GPT reply:

| Condition | Action |
|---|---|
| `VERDICT: APPROVED` | Break. Jump to **Auto-revise**. |
| Round count == cap | Break. Jump to **Auto-revise** (note unresolved issues). |
| Otherwise | Write counterreply (next section). Continue to next round. |

## Counterreply (rounds 2…N)

Write `R{N+1}_to_gpt.md` with three sections.

### Section 1: Acknowledgment

For each numbered issue GPT raised in `R{N}_from_gpt.md`, one block. Use one of these three labels:

- **Accept** — agree, will fix. State the fix concretely (what changes in the plan/code).
- **Defend** — disagree. Explain *why*, with evidence: cite line numbers, prior runs, math, constraints GPT may not have seen.
- **Clarify** — GPT's point isn't unambiguous, or assumed something not actually true. State exactly what needs clarifying and what the actual situation is.

Because the codex session persists across rounds, GPT remembers its own original wording — you don't need to quote the issue verbatim. Identify it briefly (e.g. `**Re your point 3** (bool subclass in input validation):`) and then give the response. Brevity here is for *human* monitoring of the file; GPT's memory is unaffected by how you label the issue.

Do not capitulate to every point. Defending is fine when the reasoning is sound — convergence on truth is the goal, not appeasing GPT. Equally, do not reflexively defend; check each point seriously, especially algebra/sign/unit issues which are easy to miss.

If a single issue has multiple sub-claims, address each sub-claim separately — partial agreement is common.

### Section 2: Updated artifact (only if changed)

If "Accept" items changed the plan/code, include the updated version inline. Mark what changed (use a bullet list of changes at the top). If nothing changed, say so explicitly: "No changes to the plan this round; all defenses or clarifications."

### Section 3: Continued critique prompt

Append this verbatim:

```
Review the updated plan and my responses to your earlier issues.
Push back on responses where I defended poorly — name which point.
Raise any new issues the updated plan creates. Re-issue any earlier
issue you don't think I addressed. Same numbered format and same
verdict line at the end:

  VERDICT: APPROVED
  VERDICT: ISSUES_REMAIN
```

Send through `codex exec resume "$SESSION_ID"` (see "Send a round to GPT" above for the exact invocation). Loop.

## Auto-revise (after loop ends)

When the loop exits (APPROVED or cap hit):

1. Re-read every `R*_from_gpt.md` and `R*_to_gpt.md` in numerical order.
2. Build the issue ledger: for every issue raised across all rounds, tag it `Accepted`, `Defended`, or `Unresolved` based on the latest counterreply that addressed it. If multiple rounds disagree (e.g. Round 2 accepted, Round 4 reverted to defend), use the latest tag.
3. Apply all `Accepted` fixes to the original artifact at the path recorded in STATUS.md. If the fixes conflict, prefer the most recent reasoning. Make the actual code/doc edits — this is the auto-revise step the user requested.
4. Write `FINAL_REVISION.md` in the session dir summarizing:
   - Path that was revised
   - **Addressed**: each accepted issue with a one-line note on the fix and a pointer to where it landed (file + line range or section)
   - **Defended**: each defended issue with the one-line reason
   - **Unresolved**: only present if cap hit before APPROVED — list each remaining issue with why it wasn't resolved (Claude couldn't decide / GPT and Claude disagreed irreconcilably / out of scope)
5. Update `STATUS.md`: set `Status: complete`, record final verdict and final round number.

Print a final summary to the user — at most three lines:

```
Critique loop complete after <N> rounds. Final verdict: <APPROVED|cap_hit_with_ISSUES_REMAIN>.
<K> addressed · <M> defended · <U> unresolved.
Revised: <artifact path> · Session: <session dir>
```

## File layout for one session

```
<output_dir>/CHATGPT_HANDOFF_<NN>_<topic>/
├── STATUS.md             (live state, updated every round; includes codex session ID)
├── .codex_session_id     (UUID of the persistent codex session — used by resume)
├── .codex_log_R1.txt     (raw codex stdout/stderr for round 1, kept for debugging)
├── R1_to_gpt.md          (initial handoff: context + artifact + critique prompt)
├── R1_from_gpt.md        (GPT response with VERDICT line)
├── .codex_log_R2.txt
├── R2_to_gpt.md          (counterreply: accept/defend/clarify per issue, brief identifiers)
├── R2_from_gpt.md
├── ...
└── FINAL_REVISION.md     (issue ledger + pointer to revised artifact)
```

The `.codex_session_id` and `.codex_log_R*.txt` files are dotfiles so they don't clutter directory listings, but the user can still `cat` them if anything looks off. They're also fine to delete after the loop completes — only `STATUS.md`, the `R*` files, and `FINAL_REVISION.md` are the durable record.

## Edge cases and gotchas

- **Codex CLI unavailable.** If `codex exec` errors out (CLI not configured, auth failure, model not supported, etc.), abort the loop cleanly. Update STATUS.md with `Status: error` and the error text. Do not silently fall back to "Claude pretends to be GPT" — that defeats the entire purpose of the skill. If the error is "model requires a newer version of Codex", run `npm install -g @openai/codex@latest` and retry once before giving up.
- **Empty or malformed GPT response.** If `R{N}_from_gpt.md` is empty or has no recognizable structure (no issues, no verdict), retry the round once with the same prompt. If it fails again, abort with a clear error and leave the partial files for inspection.
- **Verdict line missing.** Treat as `ISSUES_REMAIN`. Flag in the status print so the user knows GPT didn't follow format. Don't try to infer from the body — the verdict is the contract.
- **User wants to abort mid-loop.** Files persist round-by-round, so partial state is fine. Don't auto-resume in v1 — if the user comes back later, they tell Claude to continue from round N and Claude reads STATUS.md to pick up.
- **Counterreply hygiene: don't be a pushover, don't be stubborn.** The user paid for adversarial review *because* Claude has blind spots GPT can spot. But GPT also raises bogus issues. If Claude accepts every challenge, the original plan dissolves into whatever GPT said last. If Claude defends every challenge, the loop is theatre. Round-by-round honest engagement is the only mode that produces real value.
- **Token cost grows with the thread.** Codex's persistent session re-sends accumulated context to GPT each round, so per-round cost climbs with thread length. Keep the R1 context bundle dense and complete; subsequent counterreplies should focus on the new exchange, not re-derive everything. If the session is approaching 5+ rounds with growing files, pause and ask whether the topic is too broad and should be split.
- **Session storage location.** Codex stores resumable sessions under `~/.codex/` (sandbox-writable). If the host cleans `~/.codex/` between rounds (rare on a dev machine, possible in CI/sandboxed envs), `codex exec resume` will fail and the skill will fall back to transcript-concat mode. That's fine but worth knowing.
- **Output directory.** Default is `docs/` to match this user's existing pattern. If `docs/` doesn't exist or the user is working in a different repo, default to `<cwd>/critiques/` and create it. Honor any explicit user override.
- **Numbering collision.** If two sessions start in parallel (rare), they could pick the same N. Re-check the dir right before creating the session folder; if it now exists, increment again.

## Quick mental model

- **Round 1**: Claude dumps everything GPT needs into `R1_to_gpt.md`, asks for adversarial review with a verdict marker.
- **Each subsequent round**: Claude responds point-by-point in a counterreply, GPT re-evaluates.
- **Exit**: GPT verdicts APPROVED, or the cap hits.
- **After exit**: Claude actually edits the original artifact based on accepted feedback, then writes a ledger so the user can audit which feedback was accepted vs. defended and why.

The user can watch by tailing the session directory or opening files as they appear. Claude prints one short status block per round so the terminal also tells the story.
