"""Shared evaluation plumbing: paths, model ids, pricing + cost estimates, response cache, bootstrap CIs,
case loading, report helpers, and chart style.

Rules (CLAUDE.md): model ids come from settings/env (never hard-coded); no API calls here; every number that
leaves this package carries its n and a CI; dry-run outputs are labeled as such in their titles.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from shared.contracts import Case

REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = REPO_ROOT / "eval"
REPORTS_DIR = EVAL_DIR / "reports"
CACHE_DIR = EVAL_DIR / "cache"
SAMPLES_DIR = EVAL_DIR / "samples"
FIXTURES_DIR = REPO_ROOT / "pipeline" / "tests" / "fixtures" / "synthetic"
GALLERY_DIR = REPO_ROOT / "data" / "eval_galleries"

CORE_FOCAL = ("pneumothorax", "effusion", "consolidation", "atelectasis", "nodule", "mass", "fracture")

# --------------------------------------------------------------------------------------------------- pricing
# USD per million tokens (input, output), first-party Claude API list prices.
# SOURCE: the `claude-api` skill's model table ("Current Models", cached 2026-09-25), read 2026-10-05.
# Verify against https://www.anthropic.com/pricing before a live run; override with --price MODEL=IN,OUT.
PRICES_SOURCE = "claude-api skill model table (cached 2026-09-25), read 2026-10-05; CLI-overridable with --price"
DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
}
IMAGE_TOKEN_CAP = 4784  # high-resolution tier cap per image (claude-api skill, model-migration notes)
MAX_IMAGE_EDGE = 1568  # SPEC §8.2: keep every image ≤ 1568 px on the long edge
CHARS_PER_TOKEN = 3.5  # conservative text heuristic (real tokenizers average ~4 chars/token for English)


def parse_price_overrides(items: Sequence[str] | None) -> dict[str, tuple[float, float]]:
    prices = dict(DEFAULT_PRICES)
    for it in items or []:
        model, _, val = it.partition("=")
        inp, _, out = val.partition(",")
        prices[model.strip()] = (float(inp), float(out))
    return prices


def price_for(model: str, prices: dict[str, tuple[float, float]]) -> tuple[float, float]:
    if model in prices:
        return prices[model]
    raise SystemExit(
        f"No list price known for model '{model}'. Pass --price {model}=<in_usd_per_mtok>,<out_usd_per_mtok> "
        "(refusing to estimate cost without a price)."
    )


def image_tokens(width: int, height: int) -> int:
    """Image tokens ≈ w·h/750 after scaling the long edge to ≤ MAX_IMAGE_EDGE (Anthropic vision docs)."""
    s = min(1.0, MAX_IMAGE_EDGE / max(width, height))
    w, h = width * s, height * s
    return min(IMAGE_TOKEN_CAP, int(math.ceil(w * h / 750.0)))


def text_tokens(text: str) -> int:
    return int(math.ceil(len(text) / CHARS_PER_TOKEN))


@dataclass
class CallPlan:
    """One class of planned API calls (e.g. 'VLM localization', 'judge')."""

    label: str
    model: str
    n_calls: int
    input_tokens: int  # per call
    output_tokens: int  # per call, expected (incl. thinking)
    max_output_tokens: int  # per call, the max_tokens cap → worst case


@dataclass
class CostEstimate:
    rows: list[dict[str, Any]] = field(default_factory=list)
    expected_usd: float = 0.0
    worst_usd: float = 0.0

    def table(self) -> str:
        lines = [
            "| calls | model | n | in tok/call | out tok/call (exp / max) | expected $ | worst-case $ |",
            "|---|---|---|---|---|---|---|",
        ]
        for r in self.rows:
            lines.append(
                f"| {r['label']} | {r['model']} | {r['n_calls']} | {r['input_tokens']:,} | "
                f"{r['output_tokens']:,} / {r['max_output_tokens']:,} | {r['expected_usd']:.2f} | "
                f"{r['worst_usd']:.2f} |"
            )
        lines.append(f"| **total** | | | | | **{self.expected_usd:.2f}** | **{self.worst_usd:.2f}** |")
        return "\n".join(lines)


def estimate_cost(plans: Iterable[CallPlan], prices: dict[str, tuple[float, float]]) -> CostEstimate:
    est = CostEstimate()
    for p in plans:
        pin, pout = price_for(p.model, prices) if p.n_calls else (0.0, 0.0)
        exp = p.n_calls * (p.input_tokens * pin + p.output_tokens * pout) / 1e6
        worst = p.n_calls * (p.input_tokens * pin + p.max_output_tokens * pout) / 1e6
        est.rows.append({**p.__dict__, "expected_usd": exp, "worst_usd": worst})
        est.expected_usd += exp
        est.worst_usd += worst
    return est


def usage_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    prices: dict[str, tuple[float, float]],
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """Actual cost of one response from its usage block (cache reads 0.1×, writes 1.25× of input price)."""
    pin, pout = price_for(model, prices)
    return (
        input_tokens * pin + cache_read_tokens * 0.1 * pin + cache_write_tokens * 1.25 * pin + output_tokens * pout
    ) / 1e6


def check_budget(est: CostEstimate, max_cost: float, *, dry_run: bool) -> None:
    """Print the estimate; refuse (SystemExit 2) if the expected cost exceeds --max-cost. Dry runs cost $0."""
    print("Cost estimate (list prices; " + PRICES_SOURCE + "):")
    print(est.table())
    if dry_run:
        print("DRY RUN: no API calls will be made; actual cost $0.00. (Estimate above is for the live run.)")
        return
    if est.expected_usd > max_cost:
        raise SystemExit(
            f"REFUSING: expected cost ${est.expected_usd:.2f} exceeds --max-cost ${max_cost:.2f}. "
            "Lower --limit or raise --max-cost (runs > $5 need the human checkpoint)."
        )
    print(
        f"Within budget: expected ${est.expected_usd:.2f} ≤ --max-cost ${max_cost:.2f} "
        f"(worst case ${est.worst_usd:.2f}; the run also hard-stops when actual spend reaches --max-cost)."
    )


class SpendTracker:
    """Running actual spend from response usage; raises once the cap is reached (hard stop)."""

    def __init__(self, max_cost: float, prices: dict[str, tuple[float, float]]):
        import threading

        self._lock = threading.Lock()
        self.max_cost = max_cost
        self.prices = prices
        self.spent = 0.0
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0

    def add(self, model: str, usage: dict[str, Any] | None) -> None:
        u = usage or {}
        it, ot = int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0)
        cr, cw = int(u.get("cache_read_input_tokens") or 0), int(u.get("cache_creation_input_tokens") or 0)
        with self._lock:
            self.spent += usage_cost(model, it, ot, self.prices, cr, cw)
            self.calls += 1
            self.input_tokens += it + cr + cw
            self.output_tokens += ot

    def check(self) -> None:
        if self.spent >= self.max_cost:
            raise BudgetExceeded(f"actual spend ${self.spent:.2f} reached --max-cost ${self.max_cost:.2f}; stopping")


class BudgetExceeded(RuntimeError):
    pass


# --------------------------------------------------------------------------------------------------- cache
def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def stable_seed(*parts: Any) -> int:
    """Process-independent seed (Python's hash() of str is salted per process)."""
    return int(hashlib.sha256(canonical_json(list(parts)).encode()).hexdigest()[:8], 16)


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def cache_key(model: str, prompt: Any, image_hashes: Sequence[str] | str = (), extra: Any = None) -> str:
    """sha256(model, prompt, image hash(es)[, extra]). `prompt` = every non-image request part (system, text,
    schema, params) as JSON-able data; images enter only through their sha256."""
    hashes = [image_hashes] if isinstance(image_hashes, str) else list(image_hashes)
    payload = canonical_json({"model": model, "prompt": prompt, "images": hashes, "extra": extra})
    return sha256_bytes(payload.encode("utf-8"))


class ResponseCache:
    """One JSON file per request under <root>/<namespace>/<key[:2]>/<key>.json. Atomic writes; resumable.
    Dry-run mocks use a separate namespace ('.../mock') so mock outputs can never be read as live ones."""

    def __init__(self, root: Path, namespace: str):
        self.dir = Path(root) / namespace

    def path(self, key: str) -> Path:
        return self.dir / key[:2] / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        p = self.path(key)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            return None

    def put(self, key: str, record: dict[str, Any]) -> None:
        p = self.path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False, default=str))
        os.replace(tmp, p)

    def __contains__(self, key: str) -> bool:
        return self.path(key).exists()

    def observed_output_tokens(self, model: str) -> float | None:
        """Mean output tokens over cached *live* responses for this model (calibrates estimates)."""
        vals = []
        if not self.dir.exists():
            return None
        for p in self.dir.rglob("*.json"):
            try:
                r = json.loads(p.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if r.get("model") == model and not r.get("mock") and r.get("usage"):
                vals.append(float(r["usage"].get("output_tokens") or 0))
        return float(np.mean(vals)) if vals else None


# --------------------------------------------------------------------------------------------------- statistics
@dataclass
class CI:
    point: float
    lo: float
    hi: float
    n: int

    def as_dict(self) -> dict[str, float | int]:
        return {"point": self.point, "lo": self.lo, "hi": self.hi, "n": self.n}


_STATS: dict[str, Callable[..., np.ndarray]] = {"mean": np.mean, "median": np.median}


def _clean(values: Iterable[float | None]) -> np.ndarray:
    a = np.asarray([v for v in values if v is not None], dtype=float)
    return a[~np.isnan(a)]


def bootstrap_ci(
    values: Iterable[float | None], stat: str = "mean", n_boot: int = 1000, seed: int = 0, alpha: float = 0.05
) -> CI:
    """Percentile bootstrap CI over the units in `values` (None/NaN dropped). n=0 → NaNs; n=1 → degenerate."""
    a = _clean(values)
    n = int(a.size)
    if n == 0:
        return CI(float("nan"), float("nan"), float("nan"), 0)
    f = _STATS[stat]
    point = float(f(a))
    if n == 1:
        return CI(point, point, point, 1)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    boots = f(a[idx], axis=1)
    lo, hi = np.quantile(boots, [alpha / 2, 1 - alpha / 2])
    return CI(point, float(lo), float(hi), n)


def bootstrap_paired_diff(
    a: Sequence[float | None],
    b: Sequence[float | None],
    stat: str = "mean",
    n_boot: int = 1000,
    seed: int = 0,
    alpha: float = 0.05,
) -> CI:
    """CI for stat(a_i − b_i) over paired units; pairs with a missing side are dropped."""
    d = [x - y for x, y in zip(a, b) if x is not None and y is not None and not (np.isnan(x) or np.isnan(y))]
    return bootstrap_ci(d, stat=stat, n_boot=n_boot, seed=seed, alpha=alpha)


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return float("nan"), float("nan")
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, c - h), min(1.0, c + h)


def fmt_pct(ci: CI, digits: int = 0, wilson_if_degenerate: bool = True) -> str:
    """'62% [48–75], n=40'. If the percentile bootstrap collapses (all 0s or all 1s), add a Wilson interval."""
    if ci.n == 0 or math.isnan(ci.point):
        return "n/a (n=0)"
    s = f"{100 * ci.point:.{digits}f}% [{100 * ci.lo:.{digits}f}–{100 * ci.hi:.{digits}f}], n={ci.n}"
    if wilson_if_degenerate and ci.lo == ci.hi and ci.n > 1 and ci.point in (0.0, 1.0):
        wl, wh = wilson_ci(int(round(ci.point * ci.n)), ci.n)
        s += f" (Wilson {100 * wl:.0f}–{100 * wh:.0f})"
    return s


def fmt_num(ci: CI, digits: int = 2, unit: str = "") -> str:
    if ci.n == 0 or math.isnan(ci.point):
        return "n/a (n=0)"
    return f"{ci.point:.{digits}f}{unit} [{ci.lo:.{digits}f}–{ci.hi:.{digits}f}], n={ci.n}"


# --------------------------------------------------------------------------------------------------- cases
@dataclass
class CaseSource:
    name: str  # "fixtures" | "data"
    root: Path
    synthetic: bool

    @property
    def description(self) -> str:
        return "synthetic fixtures" if self.synthetic else "ChestX-Det cases (radiologist annotations)"


def resolve_source(choice: str = "auto") -> CaseSource:
    """auto → data/processed/cases.jsonl if it exists, else the synthetic fixtures."""
    from backend.app.settings import get_settings

    processed = Path(os.environ.get("BLINDSPOT_PROCESSED_DIR") or get_settings().processed_dir)
    if choice == "data" or (choice == "auto" and (processed / "cases.jsonl").exists()):
        if not (processed / "cases.jsonl").exists():
            raise SystemExit(f"--source data but {processed / 'cases.jsonl'} does not exist")
        return CaseSource("data", processed, synthetic=False)
    return CaseSource("fixtures", FIXTURES_DIR, synthetic=True)


def load_cases(src: CaseSource) -> list[Case]:
    out = []
    for line in (src.root / "cases.jsonl").read_text().splitlines():
        if line.strip():
            out.append(Case.model_validate_json(line))
    return out


def cases_for_split(cases: Sequence[Case], split: str, src: CaseSource) -> list[Case]:
    """Fixtures are all 'practice'; on fixtures every split request returns every case (documented leakage)."""
    if src.synthetic:
        return list(cases)
    return [c for c in cases if c.split == split]


# --------------------------------------------------------------------------------------------------- reports
DRY_RUN_TAG = "DRY RUN — mock model outputs"


def run_title(base: str, *, dry_run: bool, src: CaseSource) -> str:
    if dry_run:
        return f"{base} — {DRY_RUN_TAG}, {src.description}"
    if src.synthetic:
        return f"{base} — synthetic fixtures (not a result)"
    return base


def git_commit() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=5
        )
        return r.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


def provenance_lines(**kv: Any) -> list[str]:
    base = {
        "generated": now_utc(),
        "git commit": git_commit(),
        "command": "python -m "
        + " ".join([Path(sys.argv[0]).stem if sys.argv and sys.argv[0] else "?"] + sys.argv[1:]),
    }
    base.update(kv)
    return [f"- **{k}:** {v}" for k, v in base.items()]


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=_json_default))


def _json_default(o: Any) -> Any:
    if isinstance(o, CI):
        return o.as_dict()
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if hasattr(o, "model_dump"):
        return o.model_dump(mode="json", by_alias=True)
    return str(o)


def md_table(header: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    for r in rows:
        lines.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(lines)


# --------------------------------------------------------------------------------------------------- CLI
def add_common_args(ap: argparse.ArgumentParser, *, api: bool = True) -> None:
    ap.add_argument("--dry-run", action="store_true", help="no API calls; mock model outputs")
    ap.add_argument("--max-cost", type=float, default=5.0, help="USD cap: refuse if the estimate exceeds it")
    ap.add_argument("--limit", "--n", dest="limit", type=int, default=None, help="max cases/scenarios")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--source", choices=["auto", "fixtures", "data"], default="auto")
    ap.add_argument("--out-dir", type=Path, default=REPORTS_DIR)
    ap.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    ap.add_argument("--n-boot", type=int, default=1000)
    if api:
        ap.add_argument(
            "--price",
            action="append",
            default=[],
            metavar="MODEL=IN,OUT",
            help="override USD per million tokens, e.g. claude-sonnet-5-5=2,10",
        )
        ap.add_argument(
            "--yes",
            action="store_true",
            help="live runs: actually spend (without it a live invocation only prints the estimate)",
        )
        ap.add_argument("--workers", type=int, default=4)
        ap.add_argument(
            "--effort",
            choices=["default", "low", "medium", "high"],
            default="default",
            help="output_config.effort for the subject model ('default' = do not send)",
        )


def live_preflight(args: argparse.Namespace) -> bool:
    """Return True if the live run may proceed. Prints why not otherwise (never raises for missing --yes)."""
    if args.dry_run:
        return False
    from backend.app.settings import get_settings

    s = get_settings()
    if s.blindspot_offline:
        raise SystemExit("BLINDSPOT_OFFLINE=1: live eval calls are disabled. Use --dry-run.")
    if not s.anthropic_api_key and not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("No ANTHROPIC_API_KEY configured (never printed). Use --dry-run or set the key in .env.")
    if not args.yes:
        print("Estimate only. Re-run with --yes to make live API calls (human cost checkpoint first; CLAUDE.md).")
        return False
    return True


# --------------------------------------------------------------------------------------------------- charts
PALETTE = {  # dataviz skill reference palette, light mode (validated categorical order)
    "s1": "#2a78d6",  # blue
    "s2": "#eb6834",  # orange
    "s3": "#1baf7a",  # aqua
    "s4": "#eda100",  # yellow
    "s5": "#e87ba4",  # magenta
    "ink": "#0b0b0b",
    "ink2": "#52514e",
    "surface": "#fcfcfb",
    "grid": "#e4e3df",
}
SEQ_BLUES = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]


def chart_style() -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "figure.facecolor": PALETTE["surface"],
            "axes.facecolor": PALETTE["surface"],
            "savefig.facecolor": PALETTE["surface"],
            "axes.edgecolor": PALETTE["ink2"],
            "axes.labelcolor": PALETTE["ink"],
            "axes.titlecolor": PALETTE["ink"],
            "xtick.color": PALETTE["ink2"],
            "ytick.color": PALETTE["ink2"],
            "text.color": PALETTE["ink"],
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "axes.grid.axis": "y",
            "grid.color": PALETTE["grid"],
            "grid.linewidth": 0.8,
            "font.size": 12,
            "axes.titlesize": 14,
            "axes.titleweight": "bold",
            "legend.frameon": False,
        }
    )


def watermark(fig: Any, text: str | None) -> None:
    """Stamp dry-run / synthetic provenance onto a figure so a PNG can never be mistaken for a result."""
    if text:
        fig.text(
            0.5,
            0.5,
            text,
            ha="center",
            va="center",
            fontsize=26,
            color="#d03b3b",
            alpha=0.18,
            rotation=20,
            weight="bold",
        )
        fig.text(0.01, 0.01, text, ha="left", va="bottom", fontsize=9, color="#d03b3b")
