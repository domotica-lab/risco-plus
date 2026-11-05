"""Risco Plus: helpers for groups A-D (names, armed groups, combinations)."""

from __future__ import annotations

from typing import Any

from .const import RISCO_GROUPS


def parse_group_names(text: str) -> dict[str, str]:
    """Parse "B: Balconi" lines into {"B": "Balconi"}."""
    result: dict[str, str] = {}
    for line in (text or "").splitlines():
        if ":" not in line:
            continue
        group, name = line.split(":", 1)
        group = group.strip().upper()
        if group in RISCO_GROUPS and name.strip():
            result[group] = name.strip()
    return result


def group_label(group: str, names: dict[str, str]) -> str:
    """Return "B (Balconi)" or just "B"."""
    return f"{group} ({names[group]})" if group in names else group


def groups_of(value: Any) -> list[str] | None:
    """Return the groups of a mapping value ("C" or "BC"), None for arm/partial."""
    if isinstance(value, str) and value and all(g in RISCO_GROUPS for g in value):
        return list(dict.fromkeys(value))
    return None


def armed_groups(partition: Any) -> list[str]:
    """Return the armed groups of a partition; full arm = all groups."""
    if getattr(partition, "armed", False) is True:
        return list(RISCO_GROUPS)
    groups = getattr(partition, "groups", None)
    if not isinstance(groups, dict):
        return []
    return sorted(group for group, armed in groups.items() if armed)
