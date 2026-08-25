# Design QA — Artflow v0.1

## Comparison target

- Source visual truth: `/Users/andrew/.codex/generated_images/019ff10e-b71c-75f1-8e22-cb1f5ec52cc5/exec-76fee14f-8e4d-436a-b311-288153d106a9.png`
- Implementation capture: `/private/tmp/artflow_desktop.png`
- Side-by-side comparison: `/private/tmp/artflow_design_comparison.png`
- Compared state: Fire Tower loaded; fixed-board preview selected; evidence panel visible; no command running.
- Source dimensions: 1484 × 1054 px. Implementation dimensions: 1440 × 1000 px at a 1440 × 1000 CSS-px viewport and device scale factor 1. The comparison preserves each source's native density; findings exclude the 44 × 54 px viewport difference.

## Full-view comparison

The implementation preserves the selected direction's central visual workspace, left asset rail, right-hand contract/evidence column, dark slate/sand palette, and restrained rectangular surfaces. It intentionally simplifies the reference's desktop-shell affordances (menus, editor tabs, project tree) because Artflow v0.1 is a standalone local browser workbench, not an editor replacement.

Focused inspection covered the top action area, preview tabs and evidence list. The Fire Tower imagery is served from real project artifacts; no CSS-drawn or placeholder visible assets are used.

## Required fidelity surfaces

- Fonts and typography: system sans and monospace fallbacks preserve a clear hierarchy between the asset heading, evidence labels, and file hashes. The implementation is somewhat more compact than the source, which is intentional to keep the first live asset's evidence visible together.
- Spacing and layout rhythm: desktop composition keeps the source's three working zones. The preview was reduced to a 420 px ceiling so that it remains dominant without pushing all lower workflow content too far below the fold.
- Colors and visual tokens: slate canvas/surfaces, muted blue-grey dividers, warm sand action accents, and green pass state follow the source direction. No gradients are used.
- Image quality and asset fidelity: the preview uses the actual fixed-board Fire Tower review image with pixel-preserving rendering. The sidebar thumbnail uses the actual runtime PNG. No fictional asset is substituted.
- Copy and content: labels describe the current safe scope: evidence, dry-run, full on-demand `artctl verify buildings`, runtime-optional export preflight, and a deliberately blocked export step.
- Icons and controls: the implementation uses text labels for its few controls; it does not introduce a mismatched icon family. All primary controls, preview tabs, evidence links, and pipeline step selection work.

## Responsive check

At 390 × 844 CSS px, there is no horizontal overflow. The action buttons remain visible and share a 350 px row, preview width is 318 px, and the six pipeline steps expose deliberate horizontal scrolling rather than clipping their labels. No console errors were found.

## Findings

- [P3] The source mock reserves a visible lower pipeline row at desktop scale, while the live page prioritizes the real board preview and evidence list above the fold. This is acceptable for v0.1 because the current asset's review image is the primary decision surface; users can scroll to the live pipeline without losing context.

## Interaction evidence

- `运行 dry-run` produced a plan with no writes and only the runtime-optional building export preflight marked executable.
- `验证建筑合同` returned `Static-building contracts valid (1 assets; 0 not yet integrated).`
- Switching to `运行时 PNG` updated the preview.
- Browser console error check: no errors.

## Comparison history

1. Initial live comparison identified an overly permissive dry-run label: the final Godot verification was shown as executable despite v0.1's stated boundary. Fixed the adapter so only `contract_verify` can be executable. Re-tested the rendered dry-run result; `Godot 严格视觉验证` now reads `仅列出`.

## Iteration — preview navigation and controlled export

- Updated implementation capture: `/private/tmp/artflow_preview_interaction_update.png`
- Desktop viewport: 1440 × 1000 CSS px, device scale factor 1.
- Mobile viewport: 390 × 844 CSS px, device scale factor 1; no horizontal overflow.

Changes made after live review:

1. Renamed the preview overline from `当前证据` to `预览`.
2. Prevented the evidence column from stretching the preview panel. The preview now ends directly after its geometry information rather than leaving a large empty lower area.
3. Added real preview navigation: `+`/`−`, mouse-wheel zoom, pointer drag, keyboard arrow-pan, and `适配视图`. A live drag test changed the stage transform and `适配视图` returned it to `translate(0px, 0px) scale(1)`.
4. Added a controlled UI export. The button opens a purpose-built modal; it requires the exact text `fire_tower`, then the server repeats contract verification before invoking the declared `artctl export building fire_tower` command. Direct calls without the exact confirmation return HTTP 403 and do not write assets.

No new browser console errors appeared after this change. The earlier unsupported native `prompt()` error was removed by replacing it with the page modal.

## Final result

passed

## Iteration — verified version and run ledger

- Updated implementation capture: `/private/tmp/artflow_verified_workflow_final.png`
- Desktop viewport: 1440 × 1000 CSS px, device scale factor 1.
- New interaction evidence: clicking `严格视觉验证` completed `artctl verify visuals` with exit code 0 and produced a durable `visual_verify` run record. The UI showed `已验证`, the runtime PNG hash, and an expandable record containing `runtime_verify` and the input/output hashes.
- Console error check: no errors.

The run ledger remains local, records only execution facts, and has no effect on source contracts or export metadata. The implementation test suite also exercises the transition from a verified fingerprint to `stale` after an input change.
