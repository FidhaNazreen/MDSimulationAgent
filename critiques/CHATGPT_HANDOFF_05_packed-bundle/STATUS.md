# Critique Session 05 — packed-bundle

- Started: 2026-05-23
- Round cap: 5
- Current round: 4 (final)
- Latest verdict: APPROVED (R4; 4 non-blocking nits)
- Round counts: R1=8, R2=6, R3=5, R4=APPROVED
- Codex session ID: 019e54f8-c506-76a1-8bb1-e771f933bf39
- Status: complete

## Pinned decisions

- "Packed" = folder + optional .tar.gz, via `mdagent pack-bundle DIR [--archive]`.
- Wheelhouse populated via `python -m pip download` (uv has no `pip download` in 0.11.15).
- Offline install: `uv tool install --python 3.11 --no-python-downloads --force --no-cache --no-index --offline --find-links=... <spec>`.
- Online fallback (no vendor): PEP 508 form `"mdagent[propka] @ git+url"`.
- Platform/Python-specific bundles only in v0; archive name encodes both. No universal archive.
- PROPKA opt-in via `--with-propka`; metadata records it; setup.sh picks the right spec.
- Skills templated AT PACK TIME: install hint in materialized SKILL.md rewritten to `./setup.sh`.
- `setup.sh` never auto-installs uv unless `--auto-install-uv`; never auto-installs gmx.
- `--check-only` mode exits 0 on a green env without installing.
- New dep: `packaging` for pip platform-tag derivation.
