# Pilot analysis — pilot, n = 0, not powered; usability testing, not a research study

> Usability testing, not a research study: n = 0 participants with both assessments complete (0 with a participant code). Not powered; no p-values. Pre/post differences conflate practice, test familiarity and form difficulty (A vs B forms are different cases; counterbalancing by code parity only partly offsets this).

**No complete pilot data yet.** The tables below fill in once participants have finished both assessments (≥ 10 submitted cases each).

## Paired changes (post − pre; median [95% bootstrap CI], unit = participant)

| metric | pre (median) | post (median) | change (median) | improved / worse / n |
|---|---|---|---|---|
| Sensitivity (case level) | n/a | n/a | n/a | 0 / 0 / 0 |
| Specificity (case level) | n/a | n/a | n/a | 0 / 0 / 0 |
| Lesion localization fraction | n/a | n/a | n/a | 0 / 0 / 0 |
| False positives per image | n/a | n/a | n/a | 0 / 0 / 0 |
| Search errors / all misses | n/a | n/a | n/a | 0 / 0 / 0 |

## Miss-type mix (pooled counts over paired participants)

| when | search | recognition | decision | interpretation | overcall |
|---|---|---|---|---|---|
| pre | 0 | 0 | 0 | 0 | 0 |
| post | 0 | 0 | 0 | 0 | 0 |

## Form check (mean over all complete sessions on that form, regardless of order)

| form | Sensitivity (case level) | Specificity (case level) | Lesion localization fraction | False positives per image | Search errors / all misses |
|---|---|---|---|---|---|
| assess_A | n/a (n=0) | n/a (n=0) | n/a (n=0) | n/a (n=0) | n/a (n=0) |
| assess_B | n/a (n=0) | n/a (n=0) | n/a (n=0) | n/a (n=0) | n/a (n=0) |

## Per participant (anonymous codes)

(none)

## SUS

- Mean n/a (n=0); median n/a (n=0) (0–100; 68 is the commonly cited average).

## Expert review ratings (/review)

- **debriefs:** 0 ratings of 0 items by 0 reviewer(s) (roles —); accuracy n/a (n=0) / 5; teaching value n/a (n=0) / 5; safety concerns flagged: 0.
- **cards:** 0 ratings of 0 items by 0 reviewer(s) (roles —); accuracy n/a (n=0) / 5; teaching value n/a (n=0) / 5; safety concerns flagged: 0.

## Method

- Participants = learners with a participant code. Pre = their first assessment session, post = the other form. Protocol: odd codes take A first, even codes B first; deviations are listed above.
- Complete = both forms with ≥ 10 submitted cases. Incomplete participants are listed but excluded from paired statistics.
- Metrics are the app's own (backend.app.analytics.learner.case_level_stats): sensitivity = abnormal cases with any finding localized or pattern reported; specificity = normal cases with no false-positive mark or pattern; localization fraction = focal findings localized (found or mislabeled); false positives per image over all cases; search share = search errors / (search + recognition + decision).
- CIs: percentile bootstrap over participants (1000 resamples, seed 0). With n this small the intervals are wide and unstable; read them as descriptive.

## Provenance

- **generated:** 2026-10-06 02:31 UTC
- **git commit:** a66471d
- **command:** python -m pilot_analysis
- **db:** /Users/yashaswi/Downloads/blindspot/data/blindspot.sqlite
- **participants:** 0
- **paired:** 0
