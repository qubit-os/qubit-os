# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Convergence check between an SME ensemble and the Lindblad limit.

The ``lindblad`` and ``sme`` modules each carried a copy of this check from
opposite sides (``lindblad.from_sme_ensemble`` and
``SMEResult.converges_to_lindblad``); the comparison is owned by neither, so
it lives here. Those two entry points now forward to
:func:`converges_to_lindblad` below for backward compatibility.

The cross-module imports are deferred to call time so this module does not
create an import cycle with ``qubitos.lindblad``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from qubitos.lindblad import LindbladResult


def converges_to_lindblad(
    sme_result: Any,
    lindblad_result: LindbladResult,
    tol: float = 0.01,
) -> bool:
    """Return whether an SME ensemble mean agrees with a Lindblad result.

    Args:
        sme_result: Any object exposing ``mean_density_matrix`` (preferred)
            or ``final_density_matrix``.
        lindblad_result: The deterministic Lindblad solution to compare to.
        tol: Maximum trace distance for the two to count as converged.

    Returns:
        ``True`` when the trace distance between the ensemble mean (or final)
        density matrix and the Lindblad final density matrix is ``<= tol``.
    """
    from qubitos.lindblad import trace_distance

    candidate = getattr(sme_result, "mean_density_matrix", None)
    if candidate is None:
        candidate = sme_result.final_density_matrix
    return trace_distance(candidate, lindblad_result.final_density_matrix) <= tol
