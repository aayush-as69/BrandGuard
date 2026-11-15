<div align="right"><img src="../assets/brandguard-mark.svg" width="34" alt="BrandGuard"></div>

> How checked rewrites, measured image checks and the quality benchmark work, and where their limits are.

[Documentation index](README.md) · [Deployment](DEPLOYMENT.md) · [Testing](TESTING.md) · [Privacy](PRIVACY.md) · [Security](SECURITY.md)

---

# Quality guide

## Checked rewrites

Every open finding has **Rewrite options**: minimal, balanced and full, applied to the flagged span, its sentence or its paragraph.
Each option is re-checked by the same rules engine before it is shown. It must:

- add no new rule violation,
- remove the flagged problem,
- keep prices, dates and numbers identical (facts preserved),
- keep the structure (lines, bullets, greeting and sign-off).

A word diff is shown. Nothing is applied until a person clicks, and the server re-validates the text it receives, so a tampered
request is refused. Restricted findings never reveal restricted wording. Wording from the AI is used only when the author asks for
it, on masked text (see [Privacy](PRIVACY.md)); if the AI fails, the rule-based options remain. With no AI, an isolated finding may
have only one distinct option because balanced and full can be identical.

API: `GET /api/findings/<id>/rewrites`, and `POST /api/findings/<id>/decide` with `action: "rewrite"`, `text` and `strength`.

## Measured image checks

Choose an image file in the new-review form (or use a sample banner). The server reads the pixels (Pillow and numpy), stores the
measurement in `image_checks` against the uploader, and the review refers to it by `check_id`. Measured values:

| Check | Rule | How it is measured |
|---|---|---|
| Palette | G-08 | Share of pixels in colours that are neither a brand colour (CIE76 distance within `tolerance`) nor a neutral. Fails above `max_off_share`. |
| Logo | G-09 | Found by shape matching in the brand inks. Fails if missing, narrower than `min_width_pct` of the image, or with less clear space than `clear_ratio` of its height on any side. Only checked for images marked "Should show the logo". |
| Text contrast | G-06 | The text colour against the background around each area coloured like the text (worst area wins). Falls back to the typed colours when no file was read. |

Settings live in `rule_checks` (`palette`, `logo`, `contrast`) in `seed/settings.json`. Palette and logo findings have no one-click fix
(the image itself must change); text-colour findings still suggest a passing shade when one exists.

Limits: the logo is matched by shape in its brand colours, so a recoloured or heavily altered logo can be missed and a large block of
text can occasionally be mistaken for it. The text colour is estimated unless typed. Nothing identifies what a picture shows.
Measurements are kept until the database is cleaned up; images themselves are not stored.

Regenerate the sample assets with `python scripts/make_brand_assets.py`.

## Quality benchmark and learning loop (admins)

`seed/benchmark.json` holds synthetic labelled drafts. The **Quality** page reviews each one with the current knowledge base and
reports true and false positives and misses per rule: precision (alarms that were right) and recall (mistakes found). A rule below
80% precision with at least three alarms is marked for review. The AI judge is scored separately, on at most 12 drafts, only when asked.

**Suggestions** come from real decisions (dismissals, excluding carried-over ones) and from the benchmark. Kinds that can be applied
in one click: retire a glossary term, allow an all-caps acronym, add a note to a rule. Other suggestions (review a low-precision rule)
need a person. Each applied change is stored in `kb_changes` with before and after values and the benchmark runs before and after,
and can be undone from the history list. Suggestions never name a person.

Maintaining labels: labels are written from the guidelines and fact sheet, not from engine output; add a case with the expected
mistakes and run `python -m pytest tests/test_quality.py` to confirm every label points at a real rule or fact.

API (admin): `GET /api/quality`, `POST /api/benchmark/run`, `POST /api/learning/apply`, `POST /api/learning/undo`.
