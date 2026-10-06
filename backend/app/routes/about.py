"""Attributions, education-only disclaimer, limitations (SPEC §20)."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["about"])

ABOUT = {
    "name": "Blindspot",
    "tagline": "A chest X-ray perception trainer.",
    "disclaimer": "For education. Not for clinical use.",
    "datasets": [
        {
            "name": "ChestX-Det",
            "role": "Instance-level expert annotations (polygons) for 13 thoracic findings, used as the reference "
            "standard for scoring.",
            "citation": "Lian J, Liu J, Zhang S, et al. A Structure-Aware Relation Network for Thoracic Diseases "
            "Detection and Segmentation. IEEE Transactions on Medical Imaging, 2021. (ChestX-Det, Deepwise AI Lab)",
            "url": "https://github.com/Deepwise-AILab/ChestX-Det-Dataset",
        },
        {
            "name": "NIH ChestX-ray14",
            "role": "Source radiographs for ChestX-Det.",
            "citation": "Wang X, Peng Y, Lu L, Lu Z, Bagheri M, Summers RM. ChestX-ray8: Hospital-scale Chest X-ray "
            "Database and Benchmarks on Weakly-Supervised Classification and Localization of Common Thorax Diseases. "
            "IEEE CVPR 2017.",
            "acknowledgment": "Images courtesy of the NIH Clinical Center.",
            "url": "https://nihcc.app.box.com/v/ChestXray-NIHCC",
        },
        {
            "name": "TorchXRayVision",
            "role": "Anatomy segmentation (lungs, heart, hila, mediastinum) used to name zones and review areas.",
            "citation": "Cohen JP, Viviano JD, Bertin P, et al. TorchXRayVision: A library of chest X-ray datasets and "
            "models. MIDL 2022.",
            "url": "https://github.com/mlmed/torchxrayvision",
        },
    ],
    "links": [{"name": "Radiopaedia", "note": "Linked from teaching cards only; no content is copied."}],
    "tutor": "Debriefs are written by Claude (Anthropic) from facts computed by Blindspot from radiologist "
    "annotations, then checked by a deterministic validator; if a debrief fails, a template is shown instead.",
    "limitations": [
        "Where you looked is estimated from your cursor, loupe and zoom — a proxy for gaze, not eye tracking.",
        "Miss types (search, recognition, decision) are proxy classifications based on that estimate.",
        "Images come from a single US centre (NIH Clinical Center); findings may not generalise to other "
        "populations or equipment.",
        "Expert labels contain some noise, and not every abnormality on an image is necessarily annotated.",
        "Anatomical zones come from an automatic segmentation model and can be approximate.",
        "Pixel spacing is unknown for these images, so sizes are never given in centimetres.",
        "Projection (PA vs AP) is not recorded; AP films exaggerate heart size.",
        "Pilot results are from a small, unpowered usability test, not a research study.",
    ],
    "privacy": "Public, de-identified research datasets only. No patient images are uploaded.",
}


@router.get("/about")
def about() -> dict:
    return ABOUT
