# scripts/utils/io_utils.py

import json
from pathlib import Path
from typing import Any


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []

    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def write_jsonl(path: str | Path, records: list[dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        for ex in records:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")


def append_jsonl(path: str | Path, record: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()


def read_ids(path: str | Path) -> set[int]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"ID file not found: {path}")

    ids = set()
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                ids.add(int(line))
    return ids


def load_done_ids(path: str | Path) -> set[int]:
    return {
        int(ex["id"])
        for ex in read_jsonl(path)
        if "id" in ex
    }