# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Hellinger distance computation for bitstring count distributions.

The Hellinger distance H(p,q) measures similarity between two probability
distributions, bounded in [0, 1]. H=0 means identical, H=1 means orthogonal.

    H(p,q) = (1/sqrt(2)) * sqrt(sum_i (sqrt(p_i) - sqrt(q_i))^2)

Reference: https://en.wikipedia.org/wiki/Hellinger_distance
"""

from __future__ import annotations

import numpy as np

BitstringCounts = dict[str, int]


def _counts_to_probabilities(counts: BitstringCounts) -> dict[str, float]:
    """Normalize bitstring counts to a probability distribution.

    Args:
        counts: Mapping of bitstrings to observation counts.

    Returns:
        Mapping of bitstrings to probabilities summing to 1.

    Raises:
        ValueError: If counts is empty or all counts are zero.
    """
    if not counts:
        raise ValueError("counts must be non-empty")
    total = sum(counts.values())
    if total == 0:
        raise ValueError("total count is zero — cannot normalize")
    return {k: v / total for k, v in counts.items()}


def hellinger_distance(p_counts: BitstringCounts, q_counts: BitstringCounts) -> float:
    """Compute the Hellinger distance between two bitstring count distributions.

    Args:
        p_counts: First distribution as bitstring → count.
        q_counts: Second distribution as bitstring → count.

    Returns:
        Hellinger distance in [0, 1].

    Raises:
        ValueError: If either distribution is empty or all-zero.
    """
    p_probs = _counts_to_probabilities(p_counts)
    q_probs = _counts_to_probabilities(q_counts)

    all_keys = set(p_probs) | set(q_probs)

    sum_sq = 0.0
    for key in all_keys:
        sqrt_p = np.sqrt(p_probs.get(key, 0.0))
        sqrt_q = np.sqrt(q_probs.get(key, 0.0))
        sum_sq += (sqrt_p - sqrt_q) ** 2

    return float(np.sqrt(sum_sq / 2.0))


def hellinger_distance_batch(
    p_results: list[BitstringCounts],
    q_results: list[BitstringCounts],
    labels: list[str] | None = None,
) -> dict[str, float]:
    """Compute Hellinger distance for each pair of distributions.

    Args:
        p_results: List of first distributions.
        q_results: List of second distributions (same length as p_results).
        labels: Optional labels for each pair. Defaults to "pulse_0", "pulse_1", ...

    Returns:
        Mapping of label → Hellinger distance.

    Raises:
        ValueError: If p_results and q_results have different lengths,
            or labels length doesn't match.
    """
    if len(p_results) != len(q_results):
        raise ValueError(
            f"p_results and q_results must have same length, "
            f"got {len(p_results)} and {len(q_results)}"
        )
    if labels is not None and len(labels) != len(p_results):
        raise ValueError(f"labels length {len(labels)} != results length {len(p_results)}")

    if labels is None:
        labels = [f"pulse_{i}" for i in range(len(p_results))]

    return {
        label: hellinger_distance(p, q)
        for label, p, q in zip(labels, p_results, q_results, strict=True)
    }
