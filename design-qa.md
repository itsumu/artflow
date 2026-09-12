# Design QA — Artflow six-stage production workbench

## Comparison target

- Source visual truth: `/Users/andrew/.codex/generated_images/019ff10e-b71c-75f1-8e22-cb1f5ec52cc5/exec-098789b0-85e2-45d1-9f00-39e02db73814.png`
- Browser-rendered implementation: `/private/tmp/artflow-layout-qa-v3/implementation-1280x720.jpg`
- Full-view comparison evidence: `/private/tmp/artflow-layout-qa-v3/comparison-2560x760.jpg`
- Focused pipeline comparison evidence: `/private/tmp/artflow-layout-qa-v3/focused-pipeline.jpg`
- Route and state: `http://127.0.0.1:4179/`, Fire Tower, six-stage pipeline, input preparation selected.

## Viewport and normalization

- Source: 1487 × 1058 pixels, normalized proportionally into a 1280 × 720 comparison pane without cropping.
- Implementation: 1280 × 720 CSS px at device scale factor 1; capture is 1280 × 720 pixels.
- The combined comparison presents both panes at the same 1280 × 720 frame. The source is letterboxed because its aspect ratio differs from the browser viewport.
- The focused comparison isolates each pipeline rail and scales them proportionally for structural review.

## Findings

- No actionable P0, P1, or P2 findings remain.
- Typography: the implementation preserves the source hierarchy of a large asset title, compact pipeline labels, and denser inspector copy. The six longer production labels remain readable at desktop width.
- Spacing and layout rhythm: the connected pipeline rail now contains six evenly spaced core stages. Removing six review-only or utility nodes improves scanability without leaving gaps; the preview remains the dominant surface and the step inspector stays adjacent.
- Colors and visual tokens: dark navy surfaces, muted borders, amber current state, green structural status, and orange artifact links remain aligned with the selected direction.
- Image quality and asset fidelity: the implementation uses real Fire Tower production images and keeps pixel rendering sharp. No mock asset, CSS drawing, or placeholder replaces the reference imagery.
- Copy and content: review requirements are expressed in each action's confirmation plan. The input stage no longer shows a misleading empty “本步骤结果” card. The report-only Godot verification stage is explicitly labeled “运行结果”.
- Accessibility: the timeline remains button-based with numbered accessible names and state text. The input-preparation action is explicitly disabled; no horizontal body overflow was observed at 1280 px.

## Comparison history

### Pass 1 — blocked

- [P2] The twelve-node rail treated three input evidence views, two manual review checkpoints, contract preflight, and environment diagnostics as first-class production stages, making the main process harder to scan.
- [P2] Read-only steps rendered a large empty result card even though they neither produced a file nor recorded a command result.
- [P2] The export action bundled contract verification, export, and global strict visual verification, obscuring which operation the button would execute.

### Pass 2 — passed

- Consolidated input evidence into “准备输入材料”.
- Folded hard-Alpha and Aseprite review requirements into the action confirmation plans.
- Folded source/contract preflight into export, matching the existing `artctl export building` behavior.
- Kept global Godot strict visual validation as a separate sixth stage and action.
- Removed diagnostics from the production rail; project integration checks remain in the workbench header and `artctl diagnose` remains available as a utility command.
- Suppressed empty output sections for read-only stages while retaining a “运行结果” explanation for report-only command stages.
- Post-fix evidence: `/private/tmp/artflow-layout-qa-v3/comparison-2560x760.jpg` and `/private/tmp/artflow-layout-qa-v3/focused-pipeline.jpg`.

## Primary interactions tested

- Input stage: no output/result card, six input artifact links, read-only action, disabled execution button.
- Export stage: one runtime PNG output card and one fixed “导出运行时 PNG” action.
- Export plan: contains exactly one step and requires confirmation of the formal Aseprite source; no global strict visual validation is included.
- Strict visual validation stage: fixed “严格视觉验证” action and report-only result explanation.
- Pipeline adapter check: valid, six steps, five commands, four writes.
- Browser console errors checked: none.
- JavaScript syntax, JSON parsing, and repository diff checks passed.
- Python suite: 38 tests passed.

## Follow-up polish

- [P3] The selected design includes a thumbnail inside the left asset card and a green publication pill beside the title. These remain optional until the generic adapter exposes a canonical asset thumbnail.

## Implementation checklist

- [x] Reduce the production rail from twelve entries to six core stages.
- [x] Preserve manual review as action-level approval instead of standalone steps.
- [x] Separate runtime export from global strict visual validation.
- [x] Remove the empty result card from read-only input preparation.
- [x] Validate configuration, plans, browser interactions, console, and automated tests.

final result: passed
