---
title: Blindspot
colorFrom: gray
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
short_description: Chest X-ray perception trainer (education only)
---

# Blindspot

A chest X-ray perception trainer for medical students. For education only; not for clinical use.

The app is served under `/blindspot/` and is gated by an access code. Open it through
https://ysunkara.com/blindspot/ (or `/blindspot/` on this Space's own URL).

The container holds no dataset: at start it downloads a private, access-controlled data bundle. Dataset images
are not redistributed publicly. Deployment notes: `deploy/README.md` in the source repository.
