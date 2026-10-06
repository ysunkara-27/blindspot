# Blindspot — Research Brief

Compiled Monday, October 5, 2026, for the AIM × Anthropic hackathon. This is the evidence behind the design in `SPEC.md` and the ammunition for the pitch. Numbers are quoted from the sources listed in §9; re-check any number before it goes on a slide.

---

## 1. The problem, in numbers

**Most radiology misses are perceptual.** Radiology error research separates *perceptual* errors (the abnormality is on the image but not seen) from *cognitive* errors (seen but misinterpreted) [1]. A recent review of diagnostic error in imaging puts perceptual errors at roughly 60–80% of diagnostic reporting errors and names reading "blind spots" as a common objective cause [2].

**Students get little radiology training.** A narrative review of radiology clerkships reports that only about 20% of US medical schools require a radiology clerkship, unchanged between 2011 and 2018 [3]. In a multi-institutional student survey, 83% rated the amount of radiology teaching inadequate or very inadequate [4].

**Non-radiologists struggle with chest films.**
- At a teaching hospital, without clinical history only 13.2% of final-year medical students (and 40% of residents) interpreted the test chest radiographs correctly; every group had difficulty with pneumothorax [5].
- In an emergency department study, physicians and residents identified large pneumothoraces 100% of the time but small ones only 49.7% of the time [6].
- A study at Albert Einstein reviewed evidence that faulty chest X-ray interpretation by non-radiologists changes management in up to 11% of cases [7].

**The skill is trainable, and practice volume matters.** ImageSim (Boutis, Pusic and colleagues) found that deliberate practice of about 120 cases (≈1 hour) raised accuracy by about 15% on average [8]; in its pediatric MSK course the median number of cases to reach competency was 118 [9].

---

## 2. What the learning and perception science says → what we build

| Finding | Source | Design consequence |
|---|---|---|
| Immediate, case-by-case feedback over hundreds of cases produces measurable learning curves | ImageSim [8][9]; Pusic learning curves [10] | Fast loop, high case volume, learning curves on the dashboard |
| The share of normal cases in practice shifts the sensitivity/specificity trade-off (30% vs 70% normals in 103 third-year students learning CXR) | van Geel et al. [11]; Pusic et al. [12] | Normals in every session; instructor-settable prevalence (§9.2) |
| Item difficulty can be modeled psychometrically (Rasch) for radiograph cases | Pusic/Boutis (Rasch analysis of normal vs abnormal difficulty) [13] | Elo as an online Rasch model for case difficulty and learner ability |
| Learning analytics and heat-map analysis of image review behaviour reveal error-prone patterns | Thau et al. [14] | Search trace, coverage, and cohort blind-spot maps |
| False negatives split into **search** (never fixated), **recognition** (fixated briefly), **decision** (fixated at length) errors | Kundel, Nodine & Carmody 1978 [15]; Kundel et al. 1989 [16] | The miss-type engine (§7) |
| In a modern replication (mammography, 17 radiologists): ≈25% search, 25% recognition, 50% decision errors | J Med Imaging 2021 [17] | Expect decision errors to be common; teach discrimination, not just "look harder" |
| ~300 ms of dwell is enough to detect most nodules viewed directly | Perception 1980 [18] | 300 ms threshold for "visited"; recognition band starts at 300 ms |
| Radiologists actively search less than half of the lung parenchyma on CT, with large variation between readers | Rubin et al. [19] | Coverage metric; review-area coaching |
| Viewport logs (position, zoom, time) characterize diagnostic search ("scanners vs drillers") and recover the regions experts looked at | Mercan et al. [20][21]; Drew et al. [22] | Hardware-free telemetry from loupe, zoom and pan as an attention proxy |
| Satisfaction of search: finding one abnormality lowers detection of others | Berbaum et al. [23] | Multi-finding cases; "are you done?" coaching in debriefs |
| Online Elo works well for adaptive educational systems | Pelánek [24] | Elo constants and decay in `config/adaptive.yaml` |

**Honest caveat to say out loud:** cursor and viewport dwell is a *proxy* for gaze. The loupe makes it a better one (learners steer it to where they look), the viewport-log literature supports the idea, and validating it against eye tracking is roadmap work.

---

## 3. Prior art and how we differ

| System | What it does | Our difference |
|---|---|---|
| **ImageSim** (SickKids/Boutis) [8] | Validated deliberate-practice platform: commit to a diagnosis, get expert-written text + image highlighting; hundreds of cases | Feedback is hand-authored per case, which limits scale; it classifies, it doesn't analyze *how* you searched |
| **RadGame** (2025) [25] | Gamified localization (draw boxes vs PadChest-GR) with MedGemma explanations, plus report writing. In 18 medical students: localization accuracy +68% vs +17% with passive study | Strong evidence that AI-feedback localization training works. It scores *what* you marked; we diagnose *how* you missed (search / recognition / decision), coach search habits, and verify the LLM's explanations |
| **IMACT-CXR** (2025–26) [26] | Research multi-agent tutor: learner boxes, eye-tracker gaze, Bayesian knowledge tracing, lung-lobe segmentation, Socratic coaching | Closest relative. Needs gaze data from an eye tracker; we run on any laptop with a loupe-based proxy, and we report faithfulness metrics for the LLM layer |
| Radiopaedia quizzes, textbook question banks | Recognition by multiple choice | We train localization and search, not just naming |

**Positioning line:** "ImageSim proved deliberate practice works. RadGame proved AI feedback on localization beats passive study. Neither tells you *how* you missed. Blindspot does."

---

## 4. Why the LLM must be grounded (and can't be the radiologist)

- On CheXlocalize, a grid-overlay localization study found GPT-5 localized chest X-ray pathologies 49.7% of the time, GPT-4 39.1%, and MedGemma 17.7%, versus 59.9% for a task-specific CNN and 80.1% for radiologists [27].
- A systematic multimodel evaluation of visual LLMs across radiology cases reported diagnostic accuracy of only 8.1–29.2% across models, with substantial hallucination [28].
- An evaluation of GPT-4V on 100 chest radiographs concluded it was not ready for real-world interpretation [29]. Multimodal LLMs also show low sensitivity for small pneumothoraces in pneumothorax-detection studies [30].

**Design consequence:** truth comes from radiologist annotations; geometry comes from code; Claude only explains computed facts, and every explanation is validated. We will also *measure* this ourselves on our own data (SPEC §12.1–12.2), so the claim on our slide is our number, not someone else's. Newer Claude models may score well; even so, a tutor needs guaranteed truth, which grounding provides.

---

## 5. Corrections to what the team assumed

1. **"Find an API for Radiopaedia."** Radiopaedia's developer API exists for *uploading* cases and does not support downloading content, and its terms prohibit scraping or bulk automated download, explicitly including for ML/AI use [31][32]. Content is under a modified CC BY-NC-SA 3.0 license. → **Link out to Radiopaedia articles; never scrape.** Our own teaching cards (clinician-reviewed) carry the explanations.
2. **"Use the masks to train a model."** The masks *are* the answer key; we don't need a model to know where the finding is. A pretrained model (TorchXRayVision) is useful for anatomy (zones, review areas, CTR) and as a subtlety feature for difficulty. Training a detector is optional stretch work (S3), not the critical path.
3. **"Do we just trust the LLM for interpretation?"** No (see §4). Undergrads don't need radiology training to build this safely because the system never asks Claude to decide what's on the film; it asks Claude to teach what radiologists already marked, and a validator plus clinician review checks the teaching.
4. **"Is it just a quiz?"** No: it's a perception trainer — localization, search coaching, miss-type diagnosis, calibration, adaptive difficulty.

---

## 6. Datasets and licenses

| Dataset | Content | Access | License / terms | Role |
|---|---|---|---|---|
| **ChestX-Det** (Deepwise AI Lab) [33][34], HF mirror `MedOtter/ChestX-Det` [35] | ≈3,578 NIH CXRs at 1024², 13 categories, instance boxes + polygons by 3 board-certified radiologists; includes negatives | public download, no credentials | HF mirror tagged Apache-2.0; underlying images are NIH ChestX-ray14 (attribution required); cite the ChestX-Det papers | **Primary (P0)** |
| **NIH ChestX-ray14** [36] | 112,120 frontal CXRs (1024² PNG); ≈984 boxes on ≈880 images for 8 labels | public | NIH states unrestricted use with attribution (link, citation, NIH Clinical Center acknowledgment) — confirm in its README | Source images; fallback B |
| **VinDr-CXR** [37] | 18,000 PA CXRs annotated by 17 radiologists, 22 local + 6 global labels; Kaggle version: 15,000 train images read by 3 radiologists, 14 box classes (≈4,394 abnormal) | PhysioNet = credentialed (not feasible this week); Kaggle = accept competition rules | PhysioNet Credentialed Health Data License / Kaggle rules: no redistribution | Stretch S1 (multi-reader agreement) |
| **CheXlocalize** [38] | Radiologist segmentations on CheXpert val/test | Stanford AIMI agreement | research use | Reference for benchmark method only |
| **FracAtlas**, **GRAZPEDWRI-DX** | MSK fracture radiographs with localization | public | verify licenses before use | Stretch S5 |

Never commit images or masks. Keep the repo private. Don't host dataset images publicly.

---

## 7. Models and tools

| Tool | Use | Notes |
|---|---|---|
| **TorchXRayVision** [39] | `chestx_det.PSPNet` anatomical segmentation → 14 structures at 512² (clavicles, scapulae, lungs, hila, heart, aorta, diaphragm, mediastinum, trachea/"weasand", spine); DenseNet classifiers for subtlety features | `pip install torchxrayvision`; output shape `[1, 14, 512, 512]` |
| **CXAS** [40] | 159-class CXR anatomy incl. ribs and lobes | `pip install cxas`; stretch; check license |
| **Claude Sonnet 5.5** (`claude-sonnet-5-5`) | runtime debriefs, ask-the-tutor, VLM benchmark subject | vision + structured outputs + prompt caching |
| **Claude Opus 5.5 / Fable 5.1** | evaluation judge; optional benchmark subjects | cost-capped |
| **Claude Haiku 4.5** (`claude-haiku-4-5-20251001`) | optional cheap tasks | |
| **Claude Code** with Fable 5.1 | builds the system with project subagents | see README |

---

## 8. Anthropic platform facts this build relies on (verify against docs while coding)
- **Vision:** image tokens ≈ width × height / 750; images above ~1568 px on the long edge (most models) are downscaled; resize first for latency [41].
- **Structured outputs:** JSON outputs via `output_config.format` with `type: "json_schema"`; strict tool use via `strict: true`; generally available on current models; changing the format invalidates the prompt cache for that thread [42].
- **Prompt caching:** mark the stable system prefix (all teaching cards) with `cache_control`.
- **Claude Code subagents:** Markdown files in `.claude/agents/` with YAML frontmatter; `model` accepts `sonnet`, `opus`, `haiku`, `fable`, a full model ID, or `inherit`; `effort` accepts `low`–`max` depending on the model; `mcpServers` can scope a Playwright server to one subagent; subagent usage counts toward the same plan limits; `CLAUDE_CODE_SUBAGENT_MODEL` + `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` force one model onto all subagents [43].
- **Effort in Claude Code:** `/effort low | medium | high | xhigh | max | ultracode`; Claude Code defaults to `xhigh` on Fable; `ultracode` sends xhigh plus automatic multi-agent workflows [44].
- **Permission modes:** default, acceptEdits, plan, auto (a classifier reviews actions; broad allow rules are dropped while it's on), dontAsk, bypassPermissions [45].

---

## 9. Sources

1. Bruno MA, Walker EA, Abujudeh HH. Understanding and confronting our mistakes: the epidemiology of error in radiology and strategies for error reduction. *RadioGraphics* 2015;35(6):1668–1676. https://pubmed.ncbi.nlm.nih.gov/26466178/
2. Review of diagnostic errors in radiology, PMC10545608. https://pmc.ncbi.nlm.nih.gov/articles/PMC10545608/
3. Chen S, Kumaran M. Radiology clerkships from medical student perspectives (narrative review). *Int J Med Students*. https://ijms.pitt.edu/IJMS/article/download/1987/2590
4. Multi-institutional survey of medical students on radiology education. *Medical Science Educator* 2015. https://link.springer.com/doi/10.1007/s40670-015-0130-x
5. Jimah BB, et al. Competency in chest radiography interpretation by junior doctors and final year medical students at a teaching hospital. *Radiol Res Pract* 2020. https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7665931/
6. Kaymak BA, et al. Interpretation of pneumothorax on emergency department chest radiographs by emergency physicians and residents. *Eurasian J Emerg Med* 2018. https://doaj.org/article/650e3dec5cb64484a6ee7134203f64d1
7. Eisen LA, et al. Competency in chest radiography: a comparison of medical students, residents, and fellows. *J Gen Intern Med* 2006. https://pmc.ncbi.nlm.nih.gov/articles/PMC1484801
8. Boutis K, Pecaric M, Pusic M. MP20: ImageSim — performance-based medical image interpretation learning system. *CJEM* 2018. https://www.cambridge.org/core/journals/canadian-journal-of-emergency-medicine/article/mp20-imagesim-performancebased-medical-image-interpretation-learning-system/A40044E99CEFDF6B20A79CD51E755F9A
9. Boutis K, Pusic M, et al. Competency-based learning of pediatric musculoskeletal radiographs using ImageSim (Cureus poster). https://www.cureus.com/posters/1305-competency-based-learning-of-pediatric-musculoskeletal-radiographs-using-imagesim
10. Pusic M, Pecaric M, Boutis K. How much practice is enough? Using learning curves to assess the deliberate practice of radiograph interpretation. (listed with related ImageSim work) https://canadiem.org/imagesim-building-competency-for-visually-diagnosed-tests-in-emergency-medicine/
11. van Geel K, et al. Chest X-ray evaluation training: impact of normal and abnormal image ratio and instructional sequence. *Medical Education*. https://pmc.ncbi.nlm.nih.gov/articles/PMC6587445
12. Pusic M, et al. Prevalence of abnormal cases in an image bank affects the learning of radiograph interpretation. *Medical Education* 2012.
13. Interpretation difficulty of normal versus abnormal radiographs using a pediatric example (Rasch analysis). *Can Med Educ J*. https://pmc.ncbi.nlm.nih.gov/articles/PMC4830375
14. Thau E, Perez M, Pusic MV, Pecaric M, Rizzuti D, Boutis K. Image interpretation: learning analytics–informed education opportunities. *AEM Educ Train*. https://pmc.ncbi.nlm.nih.gov/articles/PMC8062270
15. Kundel HL, Nodine CF, Carmody D. Visual scanning, pattern recognition and decision-making in pulmonary nodule detection. *Invest Radiol* 1978;13(3):175–181.
16. Kundel HL, Nodine CF, Krupinski EA. Searching for lung nodules: visual dwell indicates locations of false-positive and false-negative decisions. *Invest Radiol* 1989;24(6):472–478.
17. What do experts look at and what do experts find? *J Med Imaging* 2021;8(4):045501. https://proceedings.spiedigitallibrary.org/journals/journal-of-medical-imaging/volume-8/issue-04/045501/
18. Detection of small tumors in chest films under simulated single fixations. *Perception* 1980;9(3):339. https://journals.sagepub.com/doi/abs/10.1068/p090339
19. Rubin GD, et al. Characterizing search, recognition, and decision in the detection of lung nodules on CT scans: elucidation with eye tracking. *Radiology* 2015. https://pubs.rsna.org/doi/10.1148/radiol.14132918
20. Mercan E, et al. Characterizing diagnostic search patterns in digital breast pathology: scanners and drillers. *J Digit Imaging* 2018. https://link.springer.com/article/10.1007/s10278-017-9990-5
21. Mercan E, et al. Localization of diagnostically relevant regions of interest in whole slide images (viewport tracking logs). *J Digit Imaging* 2016.
22. Drew T, et al. Scanners and drillers: characterizing expert visual search through volumetric images. *J Vis* 2013.
23. Berbaum KS, et al. Satisfaction of search in diagnostic radiology. *Invest Radiol* 1990.
24. Pelánek R. Applications of the Elo rating system in adaptive educational systems. *Computers & Education* 2016.
25. Baharoon M, Raissi S, et al. RadGame: an AI-powered platform for radiology education. arXiv:2509.13270 (2025). https://arxiv.org/abs/2509.13270
26. Le TA, Vu AM, Yang D, Awasthi A, Nguyen HV. IMACT-CXR: an interactive multi-agent conversational tutoring system for chest X-ray interpretation. arXiv:2511.15825. https://arxiv.org/abs/2511.15825
27. Gosai A, Kavishwar A. Beyond diagnosis: evaluating multimodal LLMs for pathology localization in chest radiographs. ML4H 2025; arXiv:2509.18015. https://arxiv.org/abs/2509.18015
28. Visual large language models in radiology: a systematic multimodel evaluation of diagnostic accuracy and hallucinations. PMC12842777. https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12842777/
29. Zhou Y, et al. Evaluating GPT-4 with vision on detection of radiological findings on chest radiographs. arXiv:2403.15528. https://arxiv.org/abs/2403.15528
30. Large-scale evaluation of multimodal LLMs for pneumothorax detection. *Diagn Interv Radiol* 2026. https://dirjournal.org/
31. Radiopaedia developer access (API supports uploading; does not support downloading). https://images.radiopaedia.org/developers
32. Radiopaedia Terms of Use (scraping/automated copying; licensing). https://radiopaedia.org/terms
33. Liu J, Lian J, Yu Y. ChestX-Det10: chest X-ray dataset on detection of thoracic abnormalities. arXiv:2006.10550. https://arxiv.org/abs/2006.10550
34. ChestX-Det (instance-level boxes and masks, 13 categories). arXiv:2104.10326 (as linked from the dataset card).
35. Hugging Face dataset `MedOtter/ChestX-Det`. https://huggingface.co/datasets/MedOtter/ChestX-Det
36. Wang X, et al. ChestX-ray8: hospital-scale chest X-ray database and benchmarks. CVPR 2017.
37. Nguyen HQ, et al. VinDr-CXR: an open dataset of chest X-rays with radiologist's annotations. *Sci Data* 2022;9:429. https://physionet.org/content/vindr-cxr/1.0.0/
38. Saporta A, et al. Benchmarking saliency methods for chest X-ray interpretation (CheXlocalize). *Nat Mach Intell* 2022.
39. Cohen JP, et al. TorchXRayVision: a library of chest X-ray datasets and models. MIDL 2022. https://github.com/mlmed/torchxrayvision
40. Seibold C, et al. Detailed annotations of chest X-rays via CT projection (BMVC 2022) and follow-up; CXAS package. https://pypi.org/project/cxas/
41. Anthropic docs — Vision. https://platform.claude.com/docs/en/build-with-claude/vision
42. Anthropic docs — Structured outputs. https://platform.claude.com/docs/en/build-with-claude/structured-outputs
43. Claude Code docs — Create custom subagents. https://code.claude.com/docs/en/sub-agents
44. Claude Code effort levels (overview articles; confirm in the model-configuration docs). https://claudefa.st/blog/guide/development/ultracode
45. Claude Code permission modes (overview; confirm in the docs). https://claudefa.st/blog/guide/development/permission-management
