## Claude Code context for this project

This directory mirrors the per-project state Claude Code keeps under
`~/.claude/projects/<encoded-project-path>/` so it can travel between machines
along with the repo. Nothing here is needed to run the project — it only
preserves the conversational context.

### Layout

- `transcripts/` — session JSONL logs (every Claude Code session this project
  has had on the original machine). These are append-only conversation records.
- `memory/` — Claude Code's persistent memory store for this project. Empty at
  the time of upload; populated automatically by Claude as memories are saved.

### Restoring on a new machine

After cloning the repo, sync this directory back into Claude Code's project
state. The exact destination is derived from the absolute path of the cloned
repo; for example, if you clone to `/Users/<you>/git_repos/MDSimulationAgent`,
the target is:

```
~/.claude/projects/-Users-<you>-git_repos-MDSimulationAgent/
```

(Leading slash becomes `-`, each `/` becomes `-`.)

Copy the files across:

```sh
TARGET="$HOME/.claude/projects/$(pwd | sed 's:/:-:g')"
mkdir -p "$TARGET/memory"
cp .claude-context/transcripts/*.jsonl "$TARGET/"
cp -R .claude-context/memory/. "$TARGET/memory/" 2>/dev/null || true
```

Then start `claude` from the repo root and the prior sessions will be
available via `/resume`.
