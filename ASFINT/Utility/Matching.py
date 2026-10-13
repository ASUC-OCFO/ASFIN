"""Reusable fuzzy matching helpers for organization and entity names.

The helpers are independent of processor-specific schemas. They normalize names
for comparison while leaving source values unchanged in processor outputs.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional

from rapidfuzz import fuzz


def normalize_entity_name(value: object) -> str:
    """Return a conservative comparison key for an organization/entity name."""
    if value is None:
        return ""
    text = " ".join(str(value).split())
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def unique_fuzzy_match(
    query: str,
    candidates: Iterable[str],
    *,
    threshold: float = 96.0,
    min_margin: float = 2.0,
) -> Optional[tuple[str, float]]:
    """Return a high-confidence unique fuzzy match, otherwise ``None``.

    The best candidate must clear ``threshold`` and exceed the second-best score
    by at least ``min_margin``. The margin prevents ambiguous name variants from
    being matched automatically.
    """
    unique_candidates = list(dict.fromkeys(str(c) for c in candidates if str(c)))
    if not query or not unique_candidates:
        return None

    scored: list[tuple[float, str]] = []
    for candidate in unique_candidates:
        score = max(
            fuzz.ratio(query, candidate),
            fuzz.token_set_ratio(query, candidate),
        )
        scored.append((score, candidate))

    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_candidate = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else -1.0
    if best_score < threshold or best_score - second_score < min_margin:
        return None
    return best_candidate, best_score
