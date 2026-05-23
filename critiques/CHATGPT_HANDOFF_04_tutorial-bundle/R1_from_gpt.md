1. **WHAT:** `mdagent tutorials build` is defined as regenerating files “in-place inside the package.”  
   **WHY:** Installed wheels are not a safe writable target. Site-packages may be read-only, zipped, externally managed, or shared across environments.  
   **WHAT TO DO:** Make `build` operate on an explicit source/output directory. For dev, use `--source src/mdagent/_resources/tutorials --out ...`. For users, build inside an extracted bundle only.

2. **WHAT:** The extract/build boundary is muddy.  
   **WHY:** Users need a clean copied repo; package resources should be immutable inputs. If `extract --with-pdf` internally mutates package resources first, the model breaks.  
   **WHAT TO DO:** `extract DIR` copies markdown, notebooks, `_build`, `_shared`. If `--with-pdf`, generate PDFs directly into `DIR` after extraction.

3. **WHAT:** The markdown-to-notebook splitter is underspecified.  
   **WHY:** “Split on H2 headings or code fences” will produce awkward notebooks unless rules are deterministic: shell fences, Python fences, output expectations, hidden setup, markdown metadata, and cell order all matter.  
   **WHAT TO DO:** Define a strict authoring contract: fenced `python` -> code cell, fenced `bash` -> code cell with `%%bash` or markdown-only shell blocks, all other fences remain markdown, no implicit execution outputs.

4. **WHAT:** Bash code cells are risky in notebooks.  
   **WHY:** A plain bash command in a code cell is invalid Python unless rewritten with `!`, `%%bash`, or kept as markdown. This is a likely v0 breakage.  
   **WHAT TO DO:** Pick one convention. I’d use `%%bash` cells for runnable command blocks and leave non-runnable snippets as markdown.

5. **WHAT:** The “PDFs not committed” policy conflicts with “shipping-ready tutorial bundle.”  
   **WHY:** The user explicitly asked for notebooks and PDFs. If PDFs are only generated after installing extras, then the shipped wheel does not actually contain the complete tutorial deliverable.  
   **WHAT TO DO:** Either ship PDFs in release artifacts outside the wheel, or make `mdagent tutorials extract --with-pdf` the official PDF delivery path and document that `mdagent[tutorials]` is required.

6. **WHAT:** The optional-extra syntax shown is probably wrong for `uv tool install`.  
   **WHY:** `--with tutorials` does not install the package’s `tutorials` extra in the usual sense; extras normally attach to the requirement, e.g. `git+...#egg=mdagent[tutorials]` or package-specific syntax depending on the install path.  
   **WHAT TO DO:** Verify the exact `uv` command and put that exact command in README/tests.

7. **WHAT:** WeasyPrint is reasonable, but “pure Python; no system deps once wheels install” is too optimistic.  
   **WHY:** WeasyPrint often depends on native rendering/font libraries through wheels and platform support. It is lighter than LaTeX, but not dependency-free.  
   **WHAT TO DO:** Keep WeasyPrint, but document supported Python/platform versions and add a graceful error: “Install `mdagent[tutorials]`; if PDF fails, markdown/notebooks still work.”

8. **WHAT:** PDF determinism is not just a `.gitignore` issue.  
   **WHY:** If PDFs are generated on demand, differences in fonts and WeasyPrint versions can change pagination, line wrapping, and screenshots. That affects tutorial quality.  
   **WHAT TO DO:** Pin major/minor PDF deps for releases, include CSS with explicit font fallbacks, and treat PDFs as convenience artifacts, not golden outputs.

9. **WHAT:** Markdown canonical is the right direction, but only if notebook affordances are first-class.  
   **WHY:** If the markdown cannot express notebook metadata, setup cells, kernel name, execution policy, or cell tags, the generated notebooks will feel second-rate.  
   **WHAT TO DO:** Add lightweight directives in markdown comments, e.g. `<!-- mdagent:cell bash -->`, `<!-- mdagent:skip-execute -->`, `<!-- mdagent:requires gromacs -->`.

10. **WHAT:** Empty-output notebooks are acceptable, but they must say so.  
    **WHY:** Users may assume a tutorial notebook is broken if cells produce no captured output, especially for long-running MD commands.  
    **WHAT TO DO:** Add a generated preface cell: outputs are intentionally empty; commands run locally and may require GROMACS/viewers.

11. **WHAT:** The proposed content has hidden runtime prerequisites.  
    **WHY:** Tutorials for MD simulations depend on GROMACS, possibly PROPKA, VMD/PyMOL/NGLview, and structure files. If those are not clearly separated, first-run experience fails.  
    **WHAT TO DO:** Mark each tutorial with requirements: `mdagent only`, `GROMACS required`, `viewer optional`, `PROPKA optional`.

12. **WHAT:** The old `tutorial/MD_simulation_with_agents.ipynb` is a drift trap.  
    **WHY:** A second notebook with overlapping commands will confuse contributors and users. It also violates the “one source of truth” claim.  
    **WHAT TO DO:** Either delete it, rename it as developer-only with a loud README note, or regenerate it from the same source system. Do not leave it as an independent artifact.

13. **WHAT:** `tutorials extract` and `init-project` need a composability story.  
    **WHY:** Users may want both scaffold and tutorials in one clean repo. Separate commands are fine, but collisions around `README.md`, `_shared`, examples, and configs must be deliberate.  
    **WHAT TO DO:** Keep separate commands, but add `--force`/`--no-clobber` behavior and document the recommended order.

14. **WHAT:** The source tree omits tests for the tutorial build pipeline.  
    **WHY:** A tutorial generator silently producing malformed notebooks is worse than no generator.  
    **WHAT TO DO:** Add tests that build all markdown to notebooks, parse every notebook with `nbformat.validate`, render HTML/PDF behind an optional marker, and assert extraction output contains exactly expected files.

15. **WHAT:** P1 load-bearing questions are not all the ones listed.  
    **WHY:** For v0, the real blockers are: PDF generator choice, package/extract/build mutability, and old-notebook conflict. Notebook execution, orchestrator command, sequential cells, and import-vs-subprocess are secondary.  
    **WHAT TO DO:** Decide Q1, Q7, and Q10 before implementation. Treat Q2, Q3, Q4, Q8, and Q9 as policy docs, not blockers.

**P2:** WeasyPrint is the best default among your listed options. Pandoc+LaTeX is too heavy. Browser/Chrome pipelines are heavier operationally. Keep WeasyPrint, but don’t oversell it as dependency-free or deterministic.

**P3:** Markdown should be canonical for this project. The tutorials are documentation-first and need clean PDF/README output. Notebook-canonical workflows work better when execution output is the artifact; here, execution requires external MD tooling and should not be part of release generation.

VERDICT: ISSUES_REMAIN