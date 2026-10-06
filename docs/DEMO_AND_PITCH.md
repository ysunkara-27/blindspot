# Blindspot — Team Plan, Protocols, Pitch, Demo

For the humans: Yash, Sri, Abdul-Salam (AG). Claude Code builds; this file is how the three of you win the room.

---

## 1. Roles
- **Yash — build lead.** Drives Claude Code, owns the repo and the demo laptop, integrates, makes the call when scope must be cut.
- **Sri — clinical lead.** Taxonomy sanity, teaching-card review, clinical QA of cases and overlays, the demo case playlist, radiologist reviewers, pilot recruitment at SoM.
- **AG — product and science lead.** Pitch deck and story, evidence slide, pilot protocol and running the pilot, judge Q&A prep, backup video, turning `eval/reports/REPORT.md` into slides.

---

## 2. Timeline (Mon Oct 5 → Thu Oct 8)

**Monday night**
- Yash: set up the kit (README), start Claude Code, paste the kickoff. Let W0–W2 run overnight in auto mode.
- Team chat: share this plan; agree to lock the idea by Tuesday noon.
- Sri: message radiologist contacts now (template in §4) to book 15–20 minute review slots Wednesday evening or Thursday morning.
- AG: ask organizers the questions in §3; start the deck skeleton from RESEARCH.md §1–§4.

**Tuesday**
- Before noon: 10-minute call, lock the idea.
- Sri (60–90 min): review the 13 teaching cards in `content/teaching_cards/` (or on `/review` once it exists) and fix anything clinically off. Browse `/dev` overlays for ~50 cases; flag bad cases.
- Yash: integration; first full end-to-end read with a live Claude debrief by Tuesday night.
- AG: finalize pilot protocol (§5); recruit 6–10 volunteers (AIM GroupMe, SoM friends) for Wednesday 8–10 PM; prepare the SUS form (built into the app).

**Wednesday**
- Build: dashboards, evaluations (live runs after the cost checkpoint), `/review`, pilot tooling, demo hardening.
- Sri: pick the 6 demo cases (`config/demo_playlist.yaml`, SPEC §17).
- 6:00 PM feature freeze → 8:00–10:00 PM pilot sessions (≈30 min each, 2–3 laptops in parallel).
- Late: run `pilot_analysis.py`; regenerate the report.

**Thursday**
- Morning: radiologist reviews on `/review` (§6). Fix the top issues in teaching cards only.
- Noon: final `REPORT.md`; slides filled with real numbers.
- 2:00 PM code freeze. 2–4 PM deck and a 90-second backup recording. 4–5 PM rehearse three times with a timer.
- 5:30 PM at MEB Auditorium: test the projector with projector mode, run fully local, hotspot ready. 6:00 PM demo.

---

## 3. Questions for the organizers (send tonight)
1. Judging criteria and weights? Who judges (clinicians, Darden faculty, Anthropic)?
2. Demo format: stage pitch or table demos? Time limit per team? Q&A length?
3. Submission: deadline, format (repo link, video, slides, a form)?
4. Anthropic API credits for teams?
5. Venue setup: projector resolution, HDMI/USB-C, Wi-Fi?
6. May we run a short usability session with volunteer students on Wednesday, and cite anonymous results and clinician feedback in the demo?

---

## 4. Radiologist outreach (Sri)
> Hi Dr. ___, I'm a UVA student on a team at this week's School of Medicine AI-in-Medicine hackathon with Anthropic. We're building a chest X-ray perception trainer for medical students: learners mark findings on radiologist-annotated public X-rays, and the tool explains *how* they missed what they missed (never looked there, looked past it, or looked and judged it normal). Would you have 15–20 minutes Wednesday evening or Thursday morning to rate about ten of its explanations for accuracy and teaching value on a laptop or a link? Your feedback would shape what we show at demo night on Thursday. Thank you!

---

## 5. Pilot protocol (Wednesday 8–10 PM) — usability testing, not research
- **Who:** 6–10 volunteers (ideally MS1–MS2). Voluntary; anonymous participant codes (P01…); no grades; no personal data beyond level.
- **Script (≈30 min):** 1-minute intro ("This tests our tool, not you") → **Assessment** (A for odd codes, B for even; 20 cases; no feedback) → **15 minutes of Practice** with full feedback → the **other Assessment** → SUS questionnaire (10 items) → two open questions: "What was most useful?" and "What confused you?"
- **During:** don't coach; note confusions in a shared doc.
- **After:** `uv run python -m eval.pilot_analysis` → paired changes in sensitivity, specificity, localization fraction, false positives, and miss-type mix; SUS score.
- **How to talk about it:** "In a small usability pilot (n = X), …" Never call it a study; no p-values on the slide. If we ever want to publish, we go to the UVA IRB first.

---

## 6. Radiologist review protocol (Thursday morning)
- Open `/review`. Reviewer enters name and role.
- About 10 debriefs (stratified across result types) + any teaching cards they want to check.
- Ratings: accuracy 1–5, teaching value 1–5, any safety concern, free-text correction.
- Export the CSV; the report computes means and lists corrections. Quote one sentence (with permission) on a slide.

---

## 7. Pitch (≈3.5 minutes) and slides

**Slide 1 — Hook (20 s).** A small pneumothorax on screen. "This is a thin white line. Emergency doctors catch small ones about half the time. And most radiology misses aren't knowledge gaps — 60 to 80 percent are perceptual: the finding was on the film; nobody looked there."

**Slide 2 — Problem (30 s).** Only about 1 in 5 US medical schools require radiology; 83% of students say their teaching is inadequate. Practice tools ask *what is it?* Nobody shows you *how you missed it.*

**Live demo (≈2 min) — see §8.**

**Slide 3 — Under the hood (30 s).** About 3,500 X-rays with radiologist masks → anatomy model turns pixels into apices, hila, the retrocardiac space → your loupe, zoom and pan become a search trace → the miss is classified with the Kundel taxonomy used in perception research → Claude explains, but only from computed facts, and a validator checks every word → Elo picks your next case.

**Slide 4 — Evidence we measured (40 s).** Fill from `REPORT.md`:
- "A frontier vision model asked to locate the finding hit it [X]% of the time vs the radiologists' masks" (with the label-prior baseline for context).
- "With grounding, [Y]% of debriefs were fully faithful to the radiologist truth vs [Z]% without."
- "Radiologists rated accuracy [a]/5 and teaching value [b]/5 (n = [k] debriefs)."
- "Pilot (n = [n]): search errors fell from [p]% to [q]% of misses; SUS [s]."

**Slide 5 — Why it works / where it goes (20 s).** Deliberate practice works (ImageSim: about 120 cases ≈ +15%); AI feedback beats passive study (RadGame: +68% vs +17%). We add the missing layer — coaching the search. Next: fracture radiographs, CT, and a pre-clerkship module at UVA.

**Close (10 s).** "Blindspot: find your blind spots before your patients do."

Keep slides sparse: one claim and one number per slide. Real numbers only. Credit datasets on the last slide.

---

## 8. Live demo script (rehearse the exact clicks; cache makes them instant)
1. **Case 1 — small apical pneumothorax (search-error story).** The presenter reads quickly, marks something in the lower zone, submits. Say: "Watch where I looked." The reveal shows the amber trace never reaching the apex, the cyan outline drawing in, the arrow sweeping up. Chip: *Never looked there.* Read one line of Claude's debrief aloud.
2. **Case 2 — hilar or retrocardiac finding (decision-error story).** The presenter lingers on the region but calls it normal. Chip: *Looked, judged it normal.* The debrief teaches how to tell it from vessels or the heart border. Point out the provenance badge ("reviewed by …").
3. **Hint moment (optional, 15 s).** On a new case press H: "You haven't looked at: left apex, retrocardiac." That's live coaching from the search trace.
4. **Dashboard (30 s).** The Reading log: learning curve, miss-type mix shifting from search to decision errors, blind-spot map. Say: "This is what an instructor sees for a whole class."
5. If time remains, invite a judge to read one case themselves.

**Backup:** if anything breaks, switch to the recording immediately and keep talking; if the network dies, the app is already offline-capable.

---

## 9. Judge Q&A prep
- **"Isn't this just RadGame / ImageSim?"** They proved that practice with feedback works. They score *what* you marked; we diagnose *how* you missed and coach the search itself, and we measure whether the AI's explanations are faithful.
- **"How do you know the cursor shows where they looked?"** We don't claim gaze; it's a proxy, labeled in the UI. The loupe makes it better (you steer it to where you look), and viewport-log research in digital pathology supports it. Eye-tracking validation is next.
- **"What if Claude says something wrong?"** Claude never decides what's on the film. Truth comes from radiologist masks; locations come from code; a validator checks laterality, zones and labels on every debrief, with a template fallback; clinicians review the teaching cards. Here's our faithfulness number.
- **"Data and privacy?"** Public, de-identified research datasets; no patient data; no uploads; attribution on the About page; repo private.
- **"Why Claude?"** Vision plus structured outputs make the debrief both image-aware and machine-checkable; prompt caching keeps it fast and cheap (about a cent or two per debrief); and Claude Code with subagents built the system in three days.
- **"Who pays?"** Medical schools and clerkship directors (curriculum gap), residency programs, CME for non-radiologists who read first-pass films.
- **"What did you build vs reuse?"** Reused: public datasets, a pretrained anatomy model. Built: the unified data pipeline, zone geometry, scoring, telemetry and miss-type engine, adaptive engine, tutor with validator, evaluations, and the app.
- **"Does it generalize beyond chest X-rays?"** The schema and engines are modality-agnostic; fracture radiographs are next.
- **"Bias?"** Images come mostly from one US center; we say so on the About page and plan more diverse sources.
