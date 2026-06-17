import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.utils import call_chat_completion, get_client, get_model_name


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a minimal OpenAI-compatible API connectivity check."
    )
    parser.add_argument(
        "--prompt",
        default="Reply with exactly: OK",
        help="Prompt used for the connectivity check.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=16,
        help="Maximum completion tokens for the check.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="Sampling temperature for the check.",
    )
    args = parser.parse_args()

    model = get_model_name()
    client = get_client()

    print("API connectivity check")
    print("model:", model)
    print("max_tokens:", args.max_tokens)
    print("temperature:", args.temperature)

    result = call_chat_completion(
        client,
        args.prompt,
        model=model,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        retries=0,
    )

    safe_result = {
        "finish_reason": result.get("finish_reason"),
        "usage": result.get("usage"),
        "error": result.get("error"),
        "content_preview": (result.get("content") or "")[:200],
    }
    print(json.dumps(safe_result, ensure_ascii=False, indent=2))

    if result.get("error") is not None:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
