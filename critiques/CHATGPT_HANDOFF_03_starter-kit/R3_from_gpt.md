No blocking holes remain in the starter-kit design.

1. **C1: `install-skills --force` should change behavior.**  
A semantic no-op is acceptable for v0 correctness, but it is weak UX because it advertises intent without giving users a clean-state guarantee.

Best contract:

- Default: copy current packaged skills over matching files, preserving unrelated skill directories.
- `--force`: remove and recopy only mdagent-managed skill directories.
- Best version: write `.claude/skills/.mdagent-install.json` with the installed skill names and mdagent version. On future `--force`, delete only the previously managed entries from that manifest, then copy the current packaged set.

That solves the “deleted skills linger after upgrade” case without risking user-owned skills under `.claude/skills/`.

One nit: `RunConfig.from_file` resolving `structure_path` to an absolute path means config hashes differ depending on where the starter kit is copied. That is probably acceptable for local-file workflows, but if you want location-independent hashes later, store the config base dir separately instead of mutating config data. Not a v0 blocker.

VERDICT: APPROVED