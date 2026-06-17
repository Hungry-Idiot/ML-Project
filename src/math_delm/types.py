from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentRunResult:
    records: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

