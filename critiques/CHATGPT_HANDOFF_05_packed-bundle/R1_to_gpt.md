# Round 1 handoff: a "packed" Claude-skills bundle that RUNS MD simulations

---

## Section 1 — Context bundle

### What the user just said

> "I actually wanted all the skills etc needed to run Md simulations.
> I want a packed [bundle] with Claude skills etc that can run a Md
> simulation easily using these Claude skills."

The previous slice shipped a tutorial bundle (8 markdown + 8
notebook + 8 PDF). That was reading material, not a working
artifact. The user wants the *working artifact*: a self-contained
folder a teammate can drop into a new repo and have a functioning
MD-simulation environment, driven by the Claude skills.

### What already exists (likely-reusable pieces)

1. `mdagent init-project DIR` (slice 10) materializes a working
   project: `.claude/skills/`, three example configs, a bundled
   1AKI structure, `verify.sh`, `runs/.gitkeep`. **But it requires
   `mdagent` to already be installed globally** (e.g. via
   `uv tool install ...`).
2. `mdagent install-skills --user|--project DIR` (slice 9) populates
   `.claude/skills/` independently.
3. The Claude skills themselves live inside the wheel
   (`src/mdagent/_resources/skills/`).
4. The bundled 1AKI structure
   (`src/mdagent/_resources/starter_kit/structures/1aki.pdb`) is
   already CC0 and offline-safe.
5. `uv build` produces a wheel (~few hundred KB; tested in the
   wheel-install smoke test).
6. The tutorial-bundle's markdown is shipped but separate from the
   runnable scaffold.

### What the user actually wants (my interpretation)

A folder — call it `mdagent-bundle/` — that:

- Has every Claude skill already wired in `.claude/skills/`.
- Has example configs ready to run.
- Has a bundled 1AKI structure so the first run is offline-safe.
- Has the mdagent code itself either **vendored** (a `vendor/`
  wheel) or via a **pinned install command** at the top of the
  README.
- Has a single `setup.sh` (or similar) that, on a fresh machine,
  does the full install (uv → mdagent → gromacs check) without the
  user reading a manual.
- Has a single command that runs a real MD simulation against the
  bundled structure.
- Can be moved cleanly to a new repository (`git init && git push`).

### Constraints

- macOS + Linux supported; Windows out of scope.
- GROMACS is system-side; the bundle cannot reasonably ship
  GROMACS itself (~hundreds of MB and platform-specific).
- The bundle should be runnable **offline** for the smoke test
  (so it can't depend on internet at run time, except for the
  initial `uv tool install` if mdagent isn't vendored).
- Total bundle size goal: under 5 MB extracted (compressed: under
  2 MB).

---

## Section 2 — Artifact under review

### 2.1 Proposed bundle layout (`mdagent-bundle/`)

```
mdagent-bundle/
├── README.md                          # "do this first" — 1 screen, install + first run
├── setup.sh                           # one-shot installer (uv install + gmx check)
├── run_simulation.sh                  # one-command MD: takes optional --config flag
├── .claude/skills/                    # pre-populated; no extra step needed
│   ├── md-run-workflow/SKILL.md
│   ├── md-prep-structure/SKILL.md
│   └── md-visualize/SKILL.md
├── run_configs/
│   ├── lysozyme_offline.json          # uses bundled structure; production enabled (~2 min)
│   ├── lysozyme_rcsb.json             # network fetch; full 1 ns
│   ├── propka_pH7.json                # pKa-aware example
│   └── propka_pH5.json
├── structures/
│   ├── 1aki.pdb                       # CC0 from RCSB
│   └── README.md
├── vendor/                            # OPTIONAL — pre-built wheel
│   └── mdagent-0.1.0-py3-none-any.whl
├── runs/.gitkeep                      # output dir
├── MANIFEST.json                      # bundle version + file list + hashes
└── .gitignore                         # ignores runs/* + venvs
```

### 2.2 `setup.sh` (one-shot installer)

```bash
#!/usr/bin/env bash
set -e
echo "==> Checking prerequisites…"
command -v uv >/dev/null 2>&1 || {
  echo "Installing uv via the official installer…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.cargo/bin:$PATH"
}
command -v gmx >/dev/null 2>&1 || {
  echo "GROMACS not found on PATH. Install (macOS): brew install gromacs"
  echo "Then re-run setup.sh."
  exit 1
}
# Prefer vendored wheel; fall back to git pin.
if [[ -f vendor/mdagent-0.1.0-py3-none-any.whl ]]; then
  uv tool install --force "$(pwd)/vendor/mdagent-0.1.0-py3-none-any.whl"[propka]
else
  uv tool install --force "mdagent[propka] @ git+https://github.com/FidhaNazreen/MDSimulationAgent@v0.1.0"
fi
mdagent --version
echo "==> Ready. Try: ./run_simulation.sh"
```

### 2.3 `run_simulation.sh` (one-command MD)

```bash
#!/usr/bin/env bash
set -e
CONFIG="${1:-run_configs/lysozyme_offline.json}"
RUN_ID="${2:-demo-$(date +%Y%m%d-%H%M%S)}"
mdagent doctor --gmx-required
mdagent run-workflow --runs-root ./runs --config "$CONFIG" --run-id "$RUN_ID"
mdagent inspect --run-root "./runs/$RUN_ID"
```

### 2.4 New CLI subcommand

`mdagent pack-bundle DIR [--with-vendored-wheel]` materializes the
bundle into DIR. Refuses non-empty without --force. With
--with-vendored-wheel, also builds a wheel (`uv build --wheel`) and
drops it into `DIR/vendor/`.

### 2.5 What the user does

```bash
# In the source repo:
mdagent pack-bundle ./mdagent-bundle --with-vendored-wheel
zip -r mdagent-bundle.zip ./mdagent-bundle

# On any teammate's machine:
unzip mdagent-bundle.zip && cd mdagent-bundle
./setup.sh
./run_simulation.sh
# → runs/demo-…/REPORT.md says: readiness: **ready**
```

### 2.6 Open design questions

1. **Vendoring the wheel** — yes/no? Pros: offline install, exact
   version pin. Cons: bundle size grows, drift if the source
   updates.
2. **Bundle `pip install --target ./.mdagent_venv ./vendor/*.whl`
   into a sibling venv** vs. relying on `uv tool install`. The
   former is fully self-contained but harder to keep on PATH; the
   latter requires `uv` to already be installable. I lean
   `uv tool install`.
3. **Single `mdagent pack-bundle` subcommand vs. extending
   `init-project` with `--packed`** — I lean a new subcommand
   because the artifact is structurally different (includes
   vendor/, setup.sh, run_simulation.sh).
4. **`setup.sh` autoinstalling uv via curl** — convenience vs.
   security: piping a shell installer is a real risk. Should I
   gate it behind a `--auto-install-uv` flag and otherwise just
   fail with a hint?
5. **gmx is not vendored; user must install** — should `setup.sh`
   auto-`brew install gromacs` on macOS (with confirmation)? Or
   refuse and document?
6. **What "easily" means** — is one command enough
   (`./run_simulation.sh`) or should the README show 3 examples
   (offline, RCSB, PROPKA)?
7. **Bundle vs. starter kit** — is this just `mdagent init-project`
   + setup.sh + vendor/wheel? Or is the layout substantially
   different? I lean: same layout + 2 extra files
   (setup.sh, vendor/wheel) + 1 extra config.
8. **Where the bundle lives** — `src/mdagent/_resources/packed_bundle/`
   alongside `starter_kit/`, materialized by `pack-bundle`? Or a
   separate release artifact built outside the wheel? I lean
   inside the wheel — matches every other slice's "shipping inside
   the package" pattern.
9. **MANIFEST.json** — list every file's relative path + hash for
   integrity-check at extract time? Or just version metadata? I
   lean: full file list + hash (so `mdagent pack-bundle --verify
   DIR` can detect tampering / drift).
10. **Skills frontmatter and "packed bundle is shipping-ready"** —
    the existing skills' install hints reference
    `uv tool install git+…`. In the packed bundle they should
    reference `./setup.sh` instead. Should I have a templated
    SKILL.md or maintain two copies? I lean templated: setup.sh
    rewrites the install hint inside the materialized SKILL.md
    files at unpack time.

---

## Section 3 — Critique prompt

Standard adversarial review. For each issue: WHAT / WHY / WHAT TO DO.
Number them; end with VERDICT line.

`APPROVED` if no blocking holes; nitpicks alone don't justify
`ISSUES_REMAIN`.

Specifically:

**P1.** Of the 10 open questions in Section 2.6, which 2–3 are
load-bearing for v0? My current leans: vendor the wheel (Q1),
single `pack-bundle` subcommand (Q3), inside the wheel (Q8).

**P2.** Is the proposed bundle structure (setup.sh + run_simulation.sh +
vendor/wheel + skills + configs + structure) the right shape for
"easily run MD via Claude skills"? Or should it look fundamentally
different — e.g. is there a one-script Python entrypoint that's
better than a shell script pair?

**P3.** The user's word "packed" — does that imply a literal
`.tar.gz` / `.zip` deliverable, or just "everything in one folder"?
I'm building both: the folder is the source; `pack-bundle --zip`
produces the archive.
