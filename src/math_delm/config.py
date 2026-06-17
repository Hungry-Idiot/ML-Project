from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


LEGACY_INPUT_PATH = Path("outputs/archive/legacy_20260617_150933/amo_parser_sc3_analysis_cases.jsonl")
LEGACY_OUT_PATH = Path("outputs/archive/legacy_20260617_150933/feedback_repair_benchmark.jsonl")
LEGACY_ERROR_PATH = Path("outputs/archive/legacy_20260617_150933/feedback_repair_benchmark_api_errors.jsonl")
LEGACY_OUT_MD = Path("outputs/archive/legacy_20260617_150933/feedback_repair_benchmark_report.md")
LEGACY_OUT_SUMMARY_JSON = Path("outputs/archive/legacy_20260617_150933/feedback_repair_benchmark_summary.json")

INPUT_PATH = Path("outputs/runs/latest/sc3/analysis_cases.jsonl")
OUT_PATH = Path("outputs/runs/latest/repair/feedback_repair/results.jsonl")
ERROR_PATH = Path("outputs/runs/latest/repair/feedback_repair/api_errors.jsonl")
OUT_MD = Path("outputs/runs/latest/repair/feedback_repair/report.md")
OUT_SUMMARY_JSON = Path("outputs/runs/latest/repair/feedback_repair/summary.json")

MAX_TOKENS = int(os.getenv("FEEDBACK_MAX_TOKENS", "4096"))
TEMPERATURE = float(os.getenv("FEEDBACK_TEMPERATURE", "0.7"))
SELECTOR_TEMPERATURE = float(os.getenv("FEEDBACK_SELECTOR_TEMPERATURE", "0.2"))
SLEEP_SECONDS = float(os.getenv("FEEDBACK_SLEEP", "0.5"))
USE_DIAGNOSTIC = os.getenv("FEEDBACK_USE_DIAGNOSTIC", "0") == "1"
DIAG_MAX_TOKENS = int(os.getenv("FEEDBACK_DIAG_MAX_TOKENS", "512"))
DIAG_TEMPERATURE = float(os.getenv("FEEDBACK_DIAG_TEMPERATURE", "0.2"))
USE_VERIFIED_NOTES = os.getenv("FEEDBACK_USE_VERIFIED_NOTES", "0") == "1"
USE_STRICT_EQUIV = os.getenv("FEEDBACK_USE_STRICT_EQUIV", "1") == "1"
USE_TASK_QUEUE = os.getenv("FEEDBACK_USE_TASK_QUEUE", "0") == "1"
TASK_QUEUE_MODE = os.getenv("FEEDBACK_TASK_QUEUE_MODE", "static")
ADMISSION_MAX_TOKENS = int(os.getenv("FEEDBACK_ADMISSION_MAX_TOKENS", "512"))
ADMISSION_TEMPERATURE = float(os.getenv("FEEDBACK_ADMISSION_TEMPERATURE", "0.0"))
USE_LLM_ADMISSION = os.getenv("FEEDBACK_USE_LLM_ADMISSION", "1") == "1"

LIMIT = int(os.getenv("FEEDBACK_LIMIT", "0"))
ONLY_LOW_CONF = os.getenv("FEEDBACK_ONLY_LOW_CONF", "1") == "1"
LOW_CONF_MAX_SUPPORT = int(os.getenv("FEEDBACK_LOW_CONF_MAX_SUPPORT", "1"))
ONLY_RAW_WRONG = os.getenv("FEEDBACK_ONLY_RAW_WRONG", "0") == "1"
USE_RAW_INIT = os.getenv("FEEDBACK_USE_RAW_INIT", "0") == "1"

MAX_ROUNDS = int(os.getenv("FEEDBACK_MAX_ROUNDS", "5"))
DELM_WORKERS = int(os.getenv("FEEDBACK_DELM_WORKERS", "2"))

RUN_MAIN_AGENT = os.getenv("FEEDBACK_RUN_MAIN_AGENT", "1") == "1"
RUN_DELM_LITE = os.getenv("FEEDBACK_RUN_DELM_LITE", "1") == "1"
USE_LLM_SELECTOR = os.getenv("FEEDBACK_USE_LLM_SELECTOR", "1") == "1"
VERIFIER_MAX_TOKENS = int(os.getenv("FEEDBACK_VERIFIER_MAX_TOKENS", "512"))
VERIFIER_TEMPERATURE = float(os.getenv("FEEDBACK_VERIFIER_TEMPERATURE", "0.2"))

VALID_SELECTOR_MODES = {"deterministic", "verifier", "hybrid", "llm"}
SELECTOR_MODE_RAW = os.getenv("FEEDBACK_SELECTOR_MODE")
if SELECTOR_MODE_RAW is None or not SELECTOR_MODE_RAW.strip():
    SELECTOR_MODE = "llm" if USE_LLM_SELECTOR else "deterministic"
else:
    SELECTOR_MODE = SELECTOR_MODE_RAW.strip().lower()

if SELECTOR_MODE not in VALID_SELECTOR_MODES:
    raise ValueError(
        "Invalid FEEDBACK_SELECTOR_MODE="
        f"{SELECTOR_MODE!r}. Expected one of {sorted(VALID_SELECTOR_MODES)}."
    )

TRACK_LATENT_WORKER_SOLVE = os.getenv("FEEDBACK_TRACK_LATENT_WORKER_SOLVE", "1") == "1"

STRATEGY_POOL = [
    "Try a direct algebraic derivation. Avoid repeating previous wrong answers.",
    "Try a combinatorial or counting-based approach. Check for off-by-one mistakes.",
    "Try a construction / extremal argument. Check boundary cases carefully.",
    "Try a modular, parity, or invariant-based approach if relevant.",
    "Try to verify constraints first, then derive the final answer.",
    "Try an independent solution path from scratch, not a minor variation of previous attempts.",
]

TASK_QUEUE_ROLES = [
    "numeric_checker",
    "symbolic_solver",
    "boundary_checker",
    "final_integrator",
]


def to_int(x, default: int | None = None) -> int | None:
    try:
        return int(x)
    except Exception:
        return default


def to_float(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


@dataclass
class BenchmarkConfig:
    agent: str = "both"
    model: str | None = None
    limit: int = 0
    max_rounds: int = 5
    delm_workers: int = 2
    output_root: str = "outputs/runs"
    input_cases: str = "outputs/runs/latest/sc3/analysis_cases.jsonl"

    @classmethod
    def from_env(cls) -> "BenchmarkConfig":
        return cls(
            model=os.getenv("MODEL_NAME"),
            limit=int(os.getenv("FEEDBACK_LIMIT", "0")),
            max_rounds=int(os.getenv("FEEDBACK_MAX_ROUNDS", "5")),
            delm_workers=int(os.getenv("FEEDBACK_DELM_WORKERS", "2")),
        )


def relevant_environment() -> dict[str, str]:
    prefixes = (
        "FEEDBACK_",
        "MODEL_NAME",
        "OPENAI_",
        "DEEPSEEK_",
        "REASONING_EFFORT",
        "REQUEST_TIMEOUT_SECONDS",
    )
    return {
        key: value
        for key, value in sorted(os.environ.items())
        if key.startswith(prefixes) or key in prefixes
    }
