# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Parallel sweep, checkpoint resume, and determinism tests for noise_sweep_comparison."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from qubitos.feedback import analysis
from qubitos.feedback.analysis import (
    HardwareParams,
    NoiseSweepResult,
    build_baseline_hamiltonians,
    noise_sweep_comparison,
)


def _smoke_hardware_params() -> HardwareParams:
    return HardwareParams(num_steps=12, duration_ns=12.0, adaptive_tolerance=1e-2)


def _assert_sweep_bit_equal(a: NoiseSweepResult, b: NoiseSweepResult) -> None:
    np.testing.assert_array_equal(a.noise_levels, b.noise_levels)
    assert a.methods == b.methods
    assert a.seed == b.seed
    assert a.num_trajectories == b.num_trajectories
    for m in a.methods:
        np.testing.assert_array_equal(a.mean_fidelity[m], b.mean_fidelity[m])
        np.testing.assert_array_equal(a.std_fidelity[m], b.std_fidelity[m])
    assert a.feedback_energy.keys() == b.feedback_energy.keys()
    for k, arr in a.feedback_energy.items():
        np.testing.assert_array_equal(arr, b.feedback_energy[k])


@pytest.mark.slow
def test_noise_sweep_parallel_matches_serial_smoke() -> None:
    """Smoke parity: max_workers=1 vs 4 yield identical structured output."""
    params = _smoke_hardware_params()
    noise_range = [0.2, 1.0]
    baselines = {
        "drag": build_baseline_hamiltonians("drag", params),
        "gaussian": build_baseline_hamiltonians("gaussian", params),
    }
    common = {
        "target_unitary": "X",
        "noise_range": noise_range,
        "methods": ("gaussian", "drag"),
        "num_trajectories": 4,
        "hardware_params": params,
        "seed": 42,
        "baselines": baselines,
    }
    serial = noise_sweep_comparison(**common, max_workers=1)
    parallel = noise_sweep_comparison(**common, max_workers=4)
    _assert_sweep_bit_equal(serial, parallel)


@pytest.mark.slow
def test_noise_sweep_checkpoint_resume_matches_single_shot(tmp_path: Path) -> None:
    """After a simulated kill, resume skips finished cells and matches reference."""
    params = _smoke_hardware_params()
    baselines = {
        "gaussian": build_baseline_hamiltonians("gaussian", params),
        "drag": build_baseline_hamiltonians("drag", params),
    }
    common = {
        "target_unitary": "X",
        "noise_range": [0.5, 2.0],
        "methods": ("gaussian", "drag"),
        "num_trajectories": 4,
        "hardware_params": params,
        "seed": 7,
        "baselines": baselines,
        "checkpoint_dir": tmp_path,
        "max_workers": 1,
    }

    calls: dict[str, int] = {"n": 0}
    orig_run = analysis._run_method

    def counting_run(*args: object, **kwargs: object) -> tuple[float, float, float]:
        calls["n"] += 1
        if calls["n"] >= 3:
            raise RuntimeError("simulated kill")
        return orig_run(*args, **kwargs)

    with patch.object(analysis, "_run_method", side_effect=counting_run):
        with pytest.raises(RuntimeError, match="simulated kill"):
            noise_sweep_comparison(**common)

    assert len(list(tmp_path.glob("*.npz"))) == 2

    reference = noise_sweep_comparison(
        target_unitary="X",
        noise_range=[0.5, 2.0],
        methods=("gaussian", "drag"),
        num_trajectories=4,
        hardware_params=params,
        seed=7,
        baselines=baselines,
        max_workers=1,
    )
    resumed: NoiseSweepResult
    calls_resume: dict[str, int] = {"n": 0}

    def resume_run(*args: object, **kwargs: object) -> tuple[float, float, float]:
        calls_resume["n"] += 1
        return orig_run(*args, **kwargs)

    with patch.object(analysis, "_run_method", side_effect=resume_run):
        resumed = noise_sweep_comparison(**common)

    assert calls_resume["n"] == 2

    _assert_sweep_bit_equal(resumed, reference)


def test_checkpoint_resume_prints_resuming_line_to_stdout(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Completed checkpoints are user-visible on stdout (lightweight progress signal)."""
    params = HardwareParams(num_steps=6, duration_ns=6.0, adaptive_tolerance=1e-2)
    baselines = {"gaussian": build_baseline_hamiltonians("gaussian", params)}
    common = {
        "target_unitary": "X",
        "noise_range": [1.0],
        "methods": ("gaussian",),
        "num_trajectories": 2,
        "hardware_params": params,
        "seed": 123,
        "baselines": baselines,
        "checkpoint_dir": tmp_path,
        "max_workers": 1,
    }
    noise_sweep_comparison(**common)
    assert len(list(tmp_path.glob("*.npz"))) == 1
    capsys.readouterr()
    noise_sweep_comparison(**common)
    out = capsys.readouterr().out
    assert "resuming from 1 existing checkpoints" in out


def test_max_workers_one_does_not_start_process_pool() -> None:
    params = _smoke_hardware_params()
    baselines = {"gaussian": build_baseline_hamiltonians("gaussian", params)}
    with patch.object(analysis, "ProcessPoolExecutor") as mock_pool:
        noise_sweep_comparison(
            target_unitary="X",
            noise_range=[1.0],
            methods=("gaussian",),
            num_trajectories=2,
            hardware_params=params,
            seed=0,
            baselines=baselines,
            max_workers=1,
        )
        mock_pool.assert_not_called()


def test_structured_log_writes_start_done_records(tmp_path: Path) -> None:
    """log_path produces one start and one done record per evaluated cell."""
    params = HardwareParams(num_steps=6, duration_ns=6.0, adaptive_tolerance=1e-2)
    baselines = {"gaussian": build_baseline_hamiltonians("gaussian", params)}
    log_path = tmp_path / "sweep.jsonl"
    noise_sweep_comparison(
        target_unitary="X",
        noise_range=[0.5, 1.0],
        methods=("gaussian",),
        num_trajectories=2,
        hardware_params=params,
        seed=11,
        baselines=baselines,
        max_workers=1,
        log_path=log_path,
    )
    records = [json.loads(line) for line in log_path.read_text().splitlines() if line]
    starts = [r for r in records if r["event"] == "start"]
    dones = [r for r in records if r["event"] == "done"]
    assert len(starts) == 2
    assert len(dones) == 2
    for r in starts + dones:
        assert {"ts", "noise_idx", "method_idx", "method", "noise_level"} <= r.keys()
    for r in dones:
        assert {"wall_s", "mean_fidelity"} <= r.keys()
        assert r["wall_s"] >= 0.0
    assert {r["noise_idx"] for r in dones} == {0, 1}


def test_structured_log_default_is_silent(tmp_path: Path) -> None:
    """Without log_path the sweep writes no JSONL artifact and no extra files."""
    params = HardwareParams(num_steps=6, duration_ns=6.0, adaptive_tolerance=1e-2)
    baselines = {"gaussian": build_baseline_hamiltonians("gaussian", params)}
    before = set(tmp_path.iterdir())
    noise_sweep_comparison(
        target_unitary="X",
        noise_range=[1.0],
        methods=("gaussian",),
        num_trajectories=2,
        hardware_params=params,
        seed=0,
        baselines=baselines,
        max_workers=1,
    )
    after = set(tmp_path.iterdir())
    assert before == after


def test_structured_log_resume_event_after_checkpoint(tmp_path: Path) -> None:
    """Re-running with checkpoints emits a resume record carrying the count."""
    params = HardwareParams(num_steps=6, duration_ns=6.0, adaptive_tolerance=1e-2)
    baselines = {"gaussian": build_baseline_hamiltonians("gaussian", params)}
    ckpt_dir = tmp_path / "ckpt"
    log_path = tmp_path / "sweep.jsonl"
    common = {
        "target_unitary": "X",
        "noise_range": [1.0],
        "methods": ("gaussian",),
        "num_trajectories": 2,
        "hardware_params": params,
        "seed": 0,
        "baselines": baselines,
        "checkpoint_dir": ckpt_dir,
        "max_workers": 1,
    }
    noise_sweep_comparison(**common)
    noise_sweep_comparison(**common, log_path=log_path)
    records = [json.loads(line) for line in log_path.read_text().splitlines() if line]
    resumes = [r for r in records if r["event"] == "resume"]
    assert len(resumes) == 1
    assert resumes[0]["found"] == 1


def test_structured_log_records_error_then_reraises(tmp_path: Path) -> None:
    """A worker exception emits an error record and propagates the original exception."""
    params = HardwareParams(num_steps=6, duration_ns=6.0, adaptive_tolerance=1e-2)
    baselines = {"gaussian": build_baseline_hamiltonians("gaussian", params)}
    log_path = tmp_path / "sweep.jsonl"

    def boom(*args: object, **kwargs: object) -> tuple[float, float, float]:
        raise RuntimeError("boom")

    with patch.object(analysis, "_run_method", side_effect=boom):
        with pytest.raises(RuntimeError, match="boom"):
            noise_sweep_comparison(
                target_unitary="X",
                noise_range=[1.0],
                methods=("gaussian",),
                num_trajectories=2,
                hardware_params=params,
                seed=0,
                baselines=baselines,
                max_workers=1,
                log_path=log_path,
            )
    records = [json.loads(line) for line in log_path.read_text().splitlines() if line]
    errors = [r for r in records if r["event"] == "error"]
    assert len(errors) == 1
    assert "RuntimeError" in errors[0]["error"]
    assert "boom" in errors[0]["error"]
    assert errors[0]["method"] == "gaussian"


@pytest.mark.slow
@pytest.mark.parametrize("max_workers", [1, 2, 4, 8])
def test_noise_sweep_identical_across_worker_counts(max_workers: int) -> None:
    """One (noise, method) cell must match for any worker pool size."""
    params = HardwareParams(num_steps=8, duration_ns=8.0, adaptive_tolerance=1e-2)
    baselines = {"gaussian": build_baseline_hamiltonians("gaussian", params)}
    common = {
        "target_unitary": "X",
        "noise_range": [1.0],
        "methods": ("gaussian",),
        "num_trajectories": 3,
        "hardware_params": params,
        "seed": 99,
        "baselines": baselines,
    }
    ref = noise_sweep_comparison(**common, max_workers=1)
    other = noise_sweep_comparison(**common, max_workers=max_workers)
    _assert_sweep_bit_equal(ref, other)
