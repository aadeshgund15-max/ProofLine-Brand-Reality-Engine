"""Brand Time Machine: dependency resolution (pure logic).

The API loads recorded dependency rows (never text searches) and asks which content must be
flagged when a fact/rule changes. The same rule is enforced in SQL by the router; this
function is the reference implementation and is unit-tested.

A submission is impacted when ALL hold:
  * its *current* version is the version that was reviewed (older versions are history);
  * the *latest* review run on that version used the version of the fact/rule that was
    current before the change (a re-review after the change already used the new version);
  * that run recorded a dependency on the changed fact/rule.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class DepRow:
    submission_id: str
    submission_version_id: str
    review_run_id: str
    run_started_at: str  # ISO timestamp, sortable
    fact_id: Optional[str] = None
    fact_version_id: Optional[str] = None
    rule_id: Optional[str] = None
    rule_version_id: Optional[str] = None


def resolve_impacted(
    deps: Iterable[DepRow],
    current_version_by_submission: dict[str, str],
    *,
    kind: str,                 # 'fact' | 'rule'
    entity_id: str,
    old_version_id: str,
) -> list[tuple[str, str]]:
    """Return [(submission_id, submission_version_id)] to flag, sorted for determinism."""
    deps = list(deps)
    # latest run per submission version, regardless of the changed entity
    latest: dict[str, tuple[str, str]] = {}
    for d in deps:
        cur = latest.get(d.submission_version_id)
        if cur is None or d.run_started_at > cur[0]:
            latest[d.submission_version_id] = (d.run_started_at, d.review_run_id)

    out: set[tuple[str, str]] = set()
    for d in deps:
        if current_version_by_submission.get(d.submission_id) != d.submission_version_id:
            continue
        if latest[d.submission_version_id][1] != d.review_run_id:
            continue
        if kind == "fact":
            hit = d.fact_id == entity_id and d.fact_version_id == old_version_id
        else:
            hit = d.rule_id == entity_id and d.rule_version_id == old_version_id
        if hit:
            out.add((d.submission_id, d.submission_version_id))
    return sorted(out)
