"""Attributions, education-only disclaimer, limitations (SPEC §20)."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["about"])

NIH_CITATION = (
    "Wang X, Peng Y, Lu L, Lu Z, Bagheri M, Summers RM. ChestX-ray8: Hospital-scale chest X-ray database and "
    "benchmarks on weakly-supervised classification and localization of common thorax diseases. CVPR 2017"
)

# SPEC §20 / QA issue 4: one entry per third-party source, with its licence or terms.
LICENSES = [
    {
        "name": "NIH ChestX-ray14",
        "role": "Source radiographs",
        "license": "NIH Clinical Center terms of use (public, de-identified; attribution required)",
        "url": "https://nihcc.app.box.com/v/ChestXray-NIHCC",
        "citation": NIH_CITATION,
        "acknowledgement": "NIH Clinical Center",
    },
    {
        "name": "ChestX-Det instance annotations",
        "role": "Radiologist instance masks (reference standard for scoring)",
        "provider": "Deepwise AI Lab",
        "license": "Apache-2.0",
        "url": "https://github.com/Deepwise-AILab/ChestX-Det-Dataset",
        "mirror": "https://huggingface.co/datasets/MedOtter/ChestX-Det",
        "mirror_name": "MedOtter/ChestX-Det (Hugging Face)",
    },
    {
        "name": "TorchXRayVision",
        "role": "Anatomy segmentation model",
        "license": "Apache-2.0",
        "url": "https://github.com/mlmed/torchxrayvision",
    },
    {
        "name": "Radiopaedia",
        "role": "Reference links from teaching cards",
        "license": "Links only; no Radiopaedia content is copied or scraped.",
        "url": "https://radiopaedia.org",
    },
]

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
            "license": "Apache-2.0",
            "provider": "Deepwise AI Lab",
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
            "license": "Apache-2.0",
        },
    ],
    "links": [{"name": "Radiopaedia", "note": "Linked from teaching cards only; no content is copied."}],
    "tutor": "Debriefs are written by Claude (Anthropic) from facts computed by Blindspot from radiologist "
    "annotations, then checked by a deterministic validator; if a debrief fails, a template is shown instead.",
    "limitations": [
        "Where you looked is estimated from your cursor, magnifier and zoom — a proxy for gaze, not eye tracking.",
        "The miss-type engine (search, recognition, decision) uses cursor, magnifier and zoom as a proxy for gaze; "
        "its classifications are estimates.",
        "Images come from a single US centre (NIH Clinical Center); findings may not generalise to other "
        "populations or equipment.",
        "Label noise exists even in expert annotation sets, and not every abnormality on an image is "
        "necessarily annotated.",
        "Anatomical zones come from an automatic segmentation model and can be approximate.",
        "Pixel spacing is unknown for these images, so there are no measurements in centimetres.",
        "Projection (PA vs AP) is not recorded; AP films exaggerate heart size.",
        "The cardiothoracic ratio (CTR) is measured automatically from the segmentation, and projection is not "
        "recorded, so it is a teaching aid, not a measurement.",
    ],
    "licenses": LICENSES,
    "privacy": "Public, de-identified research datasets only. No patient images are uploaded.",
}


@router.get("/about")
def about() -> dict:
    return ABOUT
