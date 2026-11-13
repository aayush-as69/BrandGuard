# UI review

Scope: the whole front end in `static/` (one `index.html`, one `style.css`, nine small scripts in `static/js/`). It was read in full and then exercised in Chromium before and after the changes. Screenshots of the final UI, all synthetic Brewline demo data, are in `docs/screenshots/` (11 screens at 1440, 768 and 390 px wide, 24 files).

## What the audit found about the product itself

The spec describes some screens for features the backend does not have. They were **not** faked in the UI:

| Spec section | Reality in this repo | Decision |
|---|---|---|
| 12 Rewrite: Minimal / Balanced / Full, with validation badges | The engine produces one suggested fix per finding (a short span replacement). There are no three strengths and no rewrite validator. | Kept one proposed fix, shown as **Original → Proposed** with a diff. Not invented. |
| 16 Guideline editor: versions, draft/publish, compare, rollback | On this branch rules were edited in place with no version store. | Edit and delete use in-page dialogs with consequences. Versioning was added afterwards on `feature/guideline-versioning` (draft, preview, publish, compare, rollback, audit). |
| 19 Benchmark: precision / recall, before / after | No benchmark code, endpoint or data exists. | No Benchmark screen was added. |
| 14 Image review with bounding boxes and measured distances | The image file is never stored; only alt text and a text/background colour pair are submitted. Logo clear space is not measured. | Contrast is shown as measured vs required with the colour pair. Overlays are not possible without storing the image. |
| 13 Diff with "protected facts" | The diff is span-level; protected facts are not tracked. | Original / Proposed with removed and added text. |

## UI audit findings

| Area | Before | Action | Result |
|---|---|---|---|
| Design tokens | Palette was defined but gradients, many literal colours and per-page values leaked through; purple/blue gradient on buttons and headings felt like a template. | One flat token set (surface, elevated, border, primary, success, warning, danger, info, muted, text), spacing scale (4 px base), type scale (12 / 13 / 14.5 / 16 / 18 / 28 px), radii. No gradients. | Every colour pair is checked at 4.5:1 or better by `tests/test_ui.py`. |
| App shell | Header and tabs, no landmarks, brand mark was not a control. | Skip link, `main` landmark, named `nav`, `aria-current` on the active tab, brand returns home. Kept the top navigation; a sidebar would add little for four sections. | Consistent shell on every screen. |
| Landing | Generic copy, no workflow shown. | Hero says what it is and what it prevents, with a real finding → evidence → fix preview, a five-step flow, what it prevents, why it is trustworthy. No fake metrics, no stock imagery. | Value proposition is visible without scrolling. |
| Login | Plain form with no client-side validation messages and no password visibility control. | In-page validation tied to the fields (`aria-invalid`, `role=alert`), show/hide password, busy state, MFA code row, back link. | Same visual language as the app. |
| Dashboard | A list plus a few counters. | "Needs your attention" first (role-aware: authors see changes requested, approvers see items waiting), then four tiles. Deliberate empty state. | Answers "what needs me now?". |
| Review workspace | Page of cards; the evidence sat inside a finding row. | Content on the left; findings, then the evidence, correction and decision, on the right. Selecting a highlight or a finding opens the same detail. "Go to decision" link. Single column on tablet and mobile, in the order content → findings → evidence → correction → decision. | The evidence is never more than one click from the text. |
| Findings | Colour carried severity. | Severity label plus shape (▲ ◆ ●), left border, decided count and progress bar, per-severity summary. | Does not rely on colour alone. |
| Evidence | Quote in the finding body. | Separate "Approved source" block: source id and type, serif quote, matched text. Submitted content, finding, source and correction are four visually distinct containers. | Authoritative but quiet. |
| Approval | A button that could fail after a click. | Readiness checklist (open findings, claim check, changes, comments, last activity). **Approve review** is disabled with a stated reason ("N findings still require a decision"). Approval and request-changes use in-page dialogs. | Approval is deliberate and explained. |
| Knowledge base | One long page. | Tabs for Guidelines / Facts / Glossary / Assets with counts, search, access level and status chips, arrow-key tab navigation, per-section empty states. | Scannable. |
| Insights | Counters. | Each disputed rule shows times triggered, dismissed, dismiss rate, the rule text and a **recommendation**. Repeated-mistakes bars. | Data → interpretation → action. |
| Admin | Role changes used a browser `prompt()` where the user had to type a role name. | In-page dialogs that state the consequence (for example "signed out immediately"). Destructive actions are red and visually separate. Table becomes stacked records on a phone. | No browser-native popups anywhere. |
| States | Ad-hoc. | Skeletons, a progress notice while a review runs, retry error cards, human-readable messages (5xx never shows server text), toast for success. | See below. |
| Debt | Browser-native `prompt()` / `confirm()` in the knowledge base (edit, delete, load demo), request changes and user roles; severity markup repeated; several chip and button variants. | Every one of those now uses the in-page `askDialog` / `confirmDialog` helper, with one `sev()` helper. The CSP is unchanged: widths and swatch colours are set from script, so no inline styles are needed. | `alert(`, `confirm(`, `prompt(` are absent from the scripts, and a browser test fails if a native dialog opens. |

## Accessibility

Issues found:
- Sign-in and user creation gave no field-level validation (empty fields went straight to the server).
- Browser `prompt()` / `confirm()` boxes for edits, deletes and role changes (no labels, no consequence text, inconsistent with the app).
- Severity relied mainly on colour.
- No skip link; no `aria-current`; headings out of order in the knowledge base.
- A decorative colour swatch flagged by axe for contrast.

Fixes:
- Errors are linked with `aria-describedby`, `aria-invalid` and `role=alert`.
- All dialogs use the `<dialog>` element: focus moves in, Escape cancels, and focus returns to the opener (tested for the approval dialog).
- Severity has text and shape.
- Skip link and `aria-current` added.
- Heading order fixed.
- The swatch is now a two-colour chip with no text.
- 44 px touch targets on coarse pointers.
- `prefers-reduced-motion` honoured.

Verification:
- axe-core 4.10 (WCAG 2.0/2.1 A and AA plus best practice) reports **0 violations** on landing, empty home, new review, workspace (also with the dismiss form open), knowledge base, insights, login, account menu, a dialog and users.
- Keyboard-only tests cover sign-in, tabbing, list items and highlights with Enter and Space, and dialog focus plus Escape.
- Every visible control has an accessible name (tested on each screen).

Remaining limitations:
- No manual test with a screen reader (NVDA, VoiceOver, JAWS). Automated checks do not replace one.
- Dark theme only; there is no light theme or forced-colours tuning.
- Findings and highlights are `role=button` elements that work with Enter and Space; a full listbox pattern was not used.

## Responsive testing

Automated at 1440, 1280, 768 and 390 px (`tests/e2e/test_ui_flow.py`): the landing page, new review, review workspace, knowledge base and insights have **no horizontal scroll**. On mobile the order content → findings → decision is asserted. Screenshots at 1440, 768 and 390 were reviewed by eye.
- Desktop: two columns, findings and decision beside the text.
- Tablet / mobile: single column, header navigation scrolls, finding rows wrap so titles stay readable, user table becomes stacked records.

Limitation: emulated viewports in Chromium only; no real devices or other browsers.

## Browser testing

Flows run in Chromium against the real server:
- Landing → Try demo → empty dashboard → New review → load demo → review → open finding → view evidence and diff → accept / dismiss with reason → submit → switch role → approve (confirmation dialog, Escape, then confirm) → approval record opens.
- Sign-in page, wrong password message, MFA row, sign-out.
- Admin: add users, load the demo knowledge base, tour.
- Full suite: **238 passed, 2 skipped** (python and browser). 5 new browser tests were added. No console errors and no native dialogs in any run.

Failures found along the way and fixed:
- Large gaps appeared between the cards in the left column because the tall findings column stretched the grid rows. The grid now uses `auto` rows with a flexible last row.
- Landing cards were misaligned because a generic `.card + .card` margin applied to grid items.
- Mobile finding titles were squeezed into a narrow column.
- Several existing tests asserted the old purple palette or native confirm; they were rewritten against the new tokens and the in-page dialog.

## Visual improvements

- **Typography:** one system stack, serif only for the document under review and for quotes, so the product and the content are never confused. Fewer sizes, fewer heavy weights.
- **Spacing:** 4 px scale used everywhere; cards 24 px (16 px on phones).
- **Navigation:** consistent header, current page marked, titles update `document.title`, focus moves to the page heading on navigation.
- **Review workspace, findings, evidence, rewrite UX:** described in the table above. The "rewrite" is the single proposed fix with an Original / Proposed diff.
- **Approval:** checklist, explicit blockers, confirmation.
- **Dashboards:** attention list first, then tiles; insights give recommendations.

## Known UI limitations

- Benchmark, three-strength rewrites, guideline versioning (create / publish / compare / rollback) and protected-fact diffs are **not implemented**, because the backend does not provide them. See the first table.
- Image review shows alt text and measured contrast only. Bounding boxes, palette samples and clear-space measurements need the image to be stored and analysed server-side.
- The dashboard has no approval-rate or benchmark-health metric, since neither is computed by the API.
- No breadcrumbs; navigation is flat (four sections), and the workspace has an "← All content" link.
- Dark theme only. Screen-reader and real-device testing not done. Cross-browser testing covers Chromium only.
- Success toasts disappear after about four seconds; they also appear in some of the screenshots.
- The per-image check works from colours the user supplies (or reads from an uploaded file); it is an aid, not a full visual audit.
