from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.math_delm.io.run_dirs import build_run_id, create_run_dirs, write_run_config, write_run_manifest
from src.math_delm import config as cfg


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Math-DeLM feedback repair into a structured run directory.")
    parser.add_argument("--agent", choices=["main", "delm", "both"], default="both")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--input-cases", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--max-rounds", type=int, default=None)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--output-root", default="outputs/runs")
    parser.add_argument("--dry-run", action="store_true", help="Prepare config/manifest and print selected cases without API calls.")
    parser.add_argument("--use-responses-api", action="store_true", help="Use OpenAI Responses API for LLM calls.")
    parser.add_argument("--reasoning-effort", choices=["none", "low", "medium", "high", "xhigh"], default=None)
    return parser.parse_args()


def _set_env_from_args(args: argparse.Namespace) -> None:
    if args.model:
        os.environ["MODEL_NAME"] = args.model
    if args.limit is not None:
        os.environ["FEEDBACK_LIMIT"] = str(args.limit)
    if args.max_rounds is not None:
        os.environ["FEEDBACK_MAX_ROUNDS"] = str(args.max_rounds)
    if args.workers is not None:
        os.environ["FEEDBACK_DELM_WORKERS"] = str(args.workers)
    if args.use_responses_api:
        os.environ["OPENAI_USE_RESPONSES_API"] = "1"
    if args.reasoning_effort:
        os.environ["OPENAI_REASONING_EFFORT"] = args.reasoning_effort


def _sync_config_from_args(args: argparse.Namespace, *, run_main: bool | None = None, run_delm: bool | None = None) -> None:
    if args.limit is not None:
        cfg.LIMIT = args.limit
    if args.max_rounds is not None:
        cfg.MAX_ROUNDS = args.max_rounds
    if args.workers is not None:
        cfg.DELM_WORKERS = args.workers
    if run_main is not None:
        cfg.RUN_MAIN_AGENT = run_main
    if run_delm is not None:
        cfg.RUN_DELM_LITE = run_delm


def _benchmark_module():
    return importlib.import_module("src.math_delm.feedback_repair_benchmark")


def _configure_legacy(
    legacy: Any,
    *,
    input_cases: Path,
    result_dir: Path,
    run_main: bool,
    run_delm: bool,
    args: argparse.Namespace,
) -> None:
    cfg.INPUT_PATH = input_cases
    cfg.OUT_PATH = result_dir / "results.jsonl"
    cfg.ERROR_PATH = result_dir / "api_errors.jsonl"
    cfg.OUT_MD = result_dir / "report.md"
    cfg.OUT_SUMMARY_JSON = result_dir / "summary.json"
    _sync_config_from_args(args, run_main=run_main, run_delm=run_delm)


def _run_agent(legacy: Any, dirs: dict[str, Path], args: argparse.Namespace, agent: str) -> None:
    if agent == "main":
        result_dir = dirs["main_agent"]
        run_main, run_delm = True, False
    elif agent == "delm":
        result_dir = dirs["delm_lite"]
        run_main, run_delm = False, True
    else:
        raise ValueError(f"Unsupported single agent run: {agent}")

    result_dir.mkdir(parents=True, exist_ok=True)
    _configure_legacy(
        legacy,
        input_cases=Path(args.input_cases),
        result_dir=result_dir,
        run_main=run_main,
        run_delm=run_delm,
        args=args,
    )
    legacy.main()


def _output_files(dirs: dict[str, Path], agent: str) -> list[str]:
    files: list[str] = []
    selected = []
    if agent in {"main", "both"}:
        selected.append(dirs["main_agent"])
    if agent in {"delm", "both"}:
        selected.append(dirs["delm_lite"])
    for directory in selected:
        files.extend(str(directory / name) for name in ("results.jsonl", "summary.json", "report.md", "api_errors.jsonl"))
    return files


def _config_dict(args: argparse.Namespace, run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "agent": args.agent,
        "model": args.model or os.getenv("MODEL_NAME"),
        "input_cases": args.input_cases,
        "limit": args.limit if args.limit is not None else int(os.getenv("FEEDBACK_LIMIT", "0")),
        "max_rounds": args.max_rounds if args.max_rounds is not None else int(os.getenv("FEEDBACK_MAX_ROUNDS", "5")),
        "delm_workers": args.workers if args.workers is not None else int(os.getenv("FEEDBACK_DELM_WORKERS", "2")),
        "output_root": args.output_root,
        "use_responses_api": bool(args.use_responses_api or os.getenv("OPENAI_USE_RESPONSES_API", "0") == "1"),
        "reasoning_effort": args.reasoning_effort or os.getenv("OPENAI_REASONING_EFFORT"),
    }


def main() -> None:
    args = parse_args()
    _set_env_from_args(args)
    _sync_config_from_args(args)

    run_id = args.run_id or build_run_id(
        dataset="amo",
        model=args.model or os.getenv("MODEL_NAME"),
        agent=args.agent,
        limit=args.limit if args.limit is not None else int(os.getenv("FEEDBACK_LIMIT", "0")),
    )
    dirs = create_run_dirs(args.output_root, run_id)
    if args.input_cases is None:
        args.input_cases = str(dirs["sc3"] / "analysis_cases.jsonl")
    config = _config_dict(args, run_id)

    write_run_config(dirs["root"], config)
    write_run_manifest(
        dirs["root"],
        {
            "run_id": run_id,
            "created_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
            "dataset": "amo",
            "model": config["model"],
            "agent": args.agent,
            "limit": config["limit"],
            "max_rounds": config["max_rounds"],
            "delm_workers": config["delm_workers"],
            "input_files": [args.input_cases],
            "output_files": _output_files(dirs, args.agent),
            "command_line_args": sys.argv[1:],
            "use_responses_api": config["use_responses_api"],
            "reasoning_effort": config["reasoning_effort"],
        },
    )

    legacy = _benchmark_module()
    if args.dry_run:
        from src.math_delm.utils import read_jsonl

        cfg.INPUT_PATH = Path(args.input_cases)
        _sync_config_from_args(
            args,
            run_main=args.agent in {"main", "both"},
            run_delm=args.agent in {"delm", "both"},
        )

        cases = read_jsonl(cfg.INPUT_PATH)
        selected_cases, _ = legacy.select_cases(cases)
        would_write = [str(dirs["root"] / "manifest.json"), str(dirs["root"] / "config.json")]
        if args.agent in {"main", "both"}:
            would_write.append(str(dirs["main_agent"] / "results.jsonl"))
        if args.agent in {"delm", "both"}:
            would_write.append(str(dirs["delm_lite"] / "results.jsonl"))

        print("[DRY RUN]")
        print("run_id:", run_id)
        print("run_dir:", dirs["root"])
        print("agent:", args.agent)
        print("input_cases:", args.input_cases)
        print("max_rounds:", cfg.MAX_ROUNDS)
        print("use_responses_api:", config["use_responses_api"])
        print("reasoning_effort:", config["reasoning_effort"])
        print("cases_selected:", len(selected_cases))
        print("would_write:")
        for path in would_write:
            print("-", path)
        return

    if args.agent in {"main", "both"}:
        _run_agent(legacy, dirs, args, "main")
    if args.agent in {"delm", "both"}:
        _run_agent(legacy, dirs, args, "delm")

    print("\nStructured run saved to:", dirs["root"])
    print("Config:", dirs["root"] / "config.json")
    print("Manifest:", dirs["root"] / "manifest.json")


if __name__ == "__main__":
    main()
