# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Noisy mock backend for statistical validation testing.

Provides a mock backend that returns slightly different results each call,
simulating shot noise and hardware variability. Useful for testing that
analysis code handles statistical fluctuations correctly.

Example:
    >>> from qubitos.testing import NoisyMockBackend
    >>>
    >>> backend = NoisyMockBackend(
    ...     num_qubits=1,
    ...     ideal_probs={"0": 0.85, "1": 0.15},
    ...     seed=42,
    ... )
    >>> result = backend.sample(num_shots=1000)
    >>> assert abs(result["0"] / 1000 - 0.85) < 0.1  # within shot noise
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from numpy.random import Generator


@dataclass
class NoisyMockBackend:
    """Mock backend that samples from a probability distribution with shot noise.

    Each call to ``sample()`` returns different counts drawn from the
    multinomial distribution defined by ``ideal_probs``.

    Attributes:
        num_qubits: Number of qubits.
        ideal_probs: Ideal measurement probabilities per bitstring.
        readout_error: Probability of bit-flip on readout (per qubit).
        seed: Random seed for reproducibility.
    """

    num_qubits: int
    ideal_probs: dict[str, float]
    readout_error: float = 0.0
    seed: int = 42
    _rng: Generator = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._rng = np.random.default_rng(self.seed)
        # Validate probabilities sum to 1
        total = sum(self.ideal_probs.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"ideal_probs must sum to 1.0 (got {total})")

    def sample(self, num_shots: int = 1000) -> dict[str, int]:
        """Sample measurement outcomes with shot noise.

        Args:
            num_shots: Number of measurement shots.

        Returns:
            Dictionary mapping bitstrings to observed counts.
        """
        bitstrings = list(self.ideal_probs.keys())
        probs = np.array([self.ideal_probs[b] for b in bitstrings])

        # Multinomial sampling
        counts_array = self._rng.multinomial(num_shots, probs)

        # Apply readout errors if configured
        if self.readout_error > 0:
            counts_array = self._apply_readout_error(bitstrings, counts_array, num_shots)

        return {b: int(c) for b, c in zip(bitstrings, counts_array, strict=True) if c > 0}

    def _apply_readout_error(
        self,
        bitstrings: list[str],
        counts: np.ndarray,
        num_shots: int,
    ) -> np.ndarray:
        """Apply symmetric readout error (bit-flip model).

        Each qubit has probability ``readout_error`` of being flipped.
        """
        # Expand counts to individual shots
        result_counts: dict[str, int] = {}
        for bs, count in zip(bitstrings, counts, strict=True):
            for _ in range(int(count)):
                # Flip each bit with probability readout_error
                flipped = ""
                for bit in bs:
                    if self._rng.random() < self.readout_error:
                        flipped += "0" if bit == "1" else "1"
                    else:
                        flipped += bit
                result_counts[flipped] = result_counts.get(flipped, 0) + 1

        # Convert back to array format
        all_bitstrings = sorted(set(bitstrings) | set(result_counts.keys()))
        return np.array([result_counts.get(b, 0) for b in all_bitstrings])

    def expected_fidelity(self, target_bitstring: str = "0") -> float:
        """Return expected measurement fidelity for a target bitstring.

        Args:
            target_bitstring: The expected correct outcome.

        Returns:
            Probability of measuring the target, accounting for readout error.
        """
        p_ideal = self.ideal_probs.get(target_bitstring, 0.0)
        if self.readout_error == 0:
            return p_ideal
        # Simple model: each bit correct with prob (1 - readout_error)
        n_bits = len(target_bitstring)
        p_correct = (1 - self.readout_error) ** n_bits
        return p_ideal * p_correct + (1 - p_ideal) * (1 - p_correct)


__all__ = ["NoisyMockBackend"]
