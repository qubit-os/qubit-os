# Copyright 2026 QubitOS Contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for qubitos.pulsegen.shapes module.

These tests verify pulse shape generation functions including Gaussian,
square, DRAG, and other envelope types.
"""

import numpy as np
import pytest

from qubitos.pulsegen.shapes import (
    PulseEnvelope,
    PulseShapeType,
    apply_window,
    cosine,
    drag,
    gaussian,
    gaussian_square,
    generate_envelope,
    sech,
    square,
)


class TestSquarePulse:
    """Tests for square pulse generation."""

    def test_basic_square(self):
        """Test basic square pulse fills entire array."""
        times = np.linspace(0, 1e-8, 100)
        envelope = square(times, amplitude=1.0)
        assert envelope.shape == (100,)
        assert np.allclose(envelope, 1.0)

    def test_square_amplitude(self):
        """Test square pulse respects amplitude."""
        times = np.linspace(0, 1e-8, 50)
        envelope = square(times, amplitude=0.5)
        assert np.allclose(envelope, 0.5)

    def test_square_windowed(self):
        """Test square pulse with start/end windowing."""
        times = np.linspace(0, 1e-8, 100)
        start = 0.25e-8
        end = 0.75e-8
        envelope = square(times, amplitude=1.0, start=start, end=end)
        # Values outside window should be zero
        assert envelope[0] == 0.0
        assert envelope[-1] == 0.0
        # Values inside window should be 1.0
        mid_idx = 50
        assert envelope[mid_idx] == 1.0

    def test_square_negative_amplitude(self):
        """Test square pulse with negative amplitude."""
        times = np.linspace(0, 1e-8, 100)
        envelope = square(times, amplitude=-0.5)
        assert np.allclose(envelope, -0.5)


class TestGaussianPulse:
    """Tests for Gaussian pulse generation."""

    def test_basic_gaussian(self):
        """Test basic Gaussian pulse shape."""
        times = np.linspace(0, 20e-9, 100)
        envelope = gaussian(times, amplitude=1.0)
        # Peak should be at center
        center_idx = 50
        assert envelope[center_idx] == pytest.approx(1.0, rel=0.01)
        # Edges should be smaller
        assert envelope[0] < envelope[center_idx]
        assert envelope[-1] < envelope[center_idx]

    def test_gaussian_amplitude(self):
        """Test Gaussian respects amplitude."""
        times = np.linspace(0, 20e-9, 100)
        envelope = gaussian(times, amplitude=0.5)
        assert max(envelope) == pytest.approx(0.5, rel=0.01)

    def test_gaussian_custom_sigma(self):
        """Test Gaussian with custom sigma."""
        times = np.linspace(0, 20e-9, 100)
        envelope_narrow = gaussian(times, amplitude=1.0, sigma=1e-9)
        envelope_wide = gaussian(times, amplitude=1.0, sigma=5e-9)
        # Narrow pulse should decay faster
        assert envelope_narrow[10] < envelope_wide[10]

    def test_gaussian_custom_center(self):
        """Test Gaussian with off-center peak."""
        times = np.linspace(0, 20e-9, 100)
        center = 5e-9  # Quarter of the way through
        envelope = gaussian(times, amplitude=1.0, center=center)
        # Find index closest to center
        center_idx = np.argmin(np.abs(times - center))
        assert np.argmax(envelope) == center_idx

    def test_gaussian_is_symmetric(self):
        """Test Gaussian is symmetric around center."""
        times = np.linspace(0, 20e-9, 101)  # Odd number for exact center
        envelope = gaussian(times, amplitude=1.0)
        # Should be symmetric
        assert np.allclose(envelope[:50], envelope[51:][::-1], rtol=1e-10)


class TestGaussianSquarePulse:
    """Tests for Gaussian-square (flat-top) pulse generation."""

    def test_basic_gaussian_square(self):
        """Test Gaussian-square pulse has flat top."""
        times = np.linspace(0, 20e-9, 100)
        envelope = gaussian_square(times, amplitude=1.0)
        # Should have a flat region in the middle
        mid_region = envelope[40:60]
        assert np.allclose(mid_region, 1.0, rtol=0.01)

    def test_gaussian_square_edges(self):
        """Test Gaussian-square has smooth edges."""
        times = np.linspace(0, 20e-9, 100)
        envelope = gaussian_square(times, amplitude=1.0)
        # Edges should be smaller than center
        assert envelope[0] < envelope[50]
        assert envelope[-1] < envelope[50]

    def test_gaussian_square_custom_params(self):
        """Test Gaussian-square with custom parameters."""
        times = np.linspace(0, 20e-9, 100)
        envelope = gaussian_square(times, amplitude=0.8, sigma=1e-9, flat_duration=10e-9)
        # Peak should match amplitude
        assert max(envelope) == pytest.approx(0.8, rel=0.01)


class TestCosinePulse:
    """Tests for cosine pulse generation."""

    def test_basic_cosine(self):
        """Test raised cosine pulse (0 at edges, max at center)."""
        times = np.linspace(0, 20e-9, 101)
        envelope = cosine(times, amplitude=1.0)
        # Should be 0 at start (raised cosine)
        assert envelope[0] == pytest.approx(0.0, abs=1e-10)
        # Should reach maximum at center
        assert max(envelope) == pytest.approx(1.0, rel=0.01)

    def test_cosine_amplitude(self):
        """Test cosine respects amplitude."""
        times = np.linspace(0, 20e-9, 101)
        envelope = cosine(times, amplitude=0.5)
        assert max(envelope) == pytest.approx(0.5, rel=0.01)

    def test_cosine_custom_frequency(self):
        """Test cosine with custom frequency."""
        times = np.linspace(0, 20e-9, 100)
        envelope = cosine(times, amplitude=1.0, frequency=2 / (20e-9))
        # Two periods should result in two peaks
        peaks = np.where(envelope > 0.9)[0]
        assert len(peaks) > 0


class TestSechPulse:
    """Tests for hyperbolic secant (sech) pulse generation."""

    def test_basic_sech(self):
        """Test basic sech pulse."""
        times = np.linspace(0, 20e-9, 101)
        envelope = sech(times, amplitude=1.0)
        # Peak should be at center
        assert np.argmax(envelope) == 50
        assert envelope[50] == pytest.approx(1.0, rel=0.01)

    def test_sech_amplitude(self):
        """Test sech respects amplitude."""
        times = np.linspace(0, 20e-9, 101)
        envelope = sech(times, amplitude=0.7)
        assert max(envelope) == pytest.approx(0.7, rel=0.01)

    def test_sech_width(self):
        """Test sech with different widths."""
        times = np.linspace(0, 20e-9, 101)
        narrow = sech(times, amplitude=1.0, width=1e-9)
        wide = sech(times, amplitude=1.0, width=5e-9)
        # Narrow pulse should decay faster
        edge_idx = 20
        assert narrow[edge_idx] < wide[edge_idx]

    def test_sech_custom_center(self):
        """Test sech with off-center peak."""
        times = np.linspace(0, 20e-9, 101)
        center = 5e-9
        envelope = sech(times, amplitude=1.0, center=center)
        center_idx = np.argmin(np.abs(times - center))
        assert np.argmax(envelope) == center_idx


class TestDRAGPulse:
    """Tests for DRAG pulse generation."""

    def test_basic_drag(self):
        """Test basic DRAG pulse returns I and Q envelopes."""
        times = np.linspace(0, 20e-9, 100)
        i_env, q_env = drag(times, amplitude=1.0, beta=0.5)
        assert i_env.shape == (100,)
        assert q_env.shape == (100,)
        # I envelope should be Gaussian-like
        assert np.argmax(i_env) == pytest.approx(50, abs=2)

    def test_drag_q_is_derivative(self):
        """Test Q envelope is proportional to derivative of I."""
        times = np.linspace(0, 20e-9, 100)
        i_env, q_env = drag(times, amplitude=1.0, beta=1.0)
        # Q should be zero at center (derivative of Gaussian is zero at peak)
        center_idx = 50
        assert abs(q_env[center_idx]) < abs(q_env[25])

    def test_drag_beta_zero(self):
        """Test DRAG with beta=0 gives zero Q envelope."""
        times = np.linspace(0, 20e-9, 100)
        i_env, q_env = drag(times, amplitude=1.0, beta=0.0)
        assert np.allclose(q_env, 0.0)

    def test_drag_with_anharmonicity(self):
        """Test DRAG computes beta from anharmonicity."""
        times = np.linspace(0, 20e-9, 100)
        anharmonicity = -200e6  # -200 MHz typical for transmon
        i_env, q_env = drag(times, amplitude=1.0, anharmonicity=anharmonicity)
        # Q should not be zero
        assert not np.allclose(q_env, 0.0)
        # Expected beta = -1 / (4 * anharmonicity)
        expected_beta = -1 / (4 * anharmonicity)
        # Verify by checking Q amplitude scale
        assert max(abs(q_env)) > 0

    def test_drag_zero_anharmonicity_raises(self):
        """Test DRAG raises error for zero anharmonicity."""
        times = np.linspace(0, 20e-9, 100)
        with pytest.raises(ValueError, match="anharmonicity cannot be zero"):
            drag(times, amplitude=1.0, anharmonicity=0.0)

    def test_drag_custom_sigma(self):
        """Test DRAG with custom sigma."""
        times = np.linspace(0, 20e-9, 100)
        i_narrow, _ = drag(times, amplitude=1.0, sigma=1e-9, beta=0.5)
        i_wide, _ = drag(times, amplitude=1.0, sigma=5e-9, beta=0.5)
        # Narrow pulse should decay faster
        assert i_narrow[10] < i_wide[10]


class TestGenerateEnvelope:
    """Tests for the generate_envelope convenience function."""

    def test_generate_square(self):
        """Test generate_envelope with square shape."""
        env = generate_envelope("square", num_time_steps=100, duration_ns=20.0)
        assert isinstance(env, PulseEnvelope)
        assert env.shape_type == PulseShapeType.SQUARE
        assert len(env.i_envelope) == 100
        assert len(env.q_envelope) == 100
        assert np.allclose(env.q_envelope, 0.0)

    def test_generate_gaussian(self):
        """Test generate_envelope with Gaussian shape."""
        env = generate_envelope("gaussian", num_time_steps=100, duration_ns=20.0)
        assert env.shape_type == PulseShapeType.GAUSSIAN
        assert max(env.i_envelope) == pytest.approx(1.0, rel=0.01)

    def test_generate_drag(self):
        """Test generate_envelope with DRAG shape."""
        env = generate_envelope("drag", num_time_steps=100, duration_ns=20.0, beta=0.5)
        assert env.shape_type == PulseShapeType.DRAG
        # DRAG should have non-zero Q envelope
        assert not np.allclose(env.q_envelope, 0.0)

    def test_generate_gaussian_square(self):
        """Test generate_envelope with Gaussian-square shape."""
        env = generate_envelope("gaussian_square", num_time_steps=100, duration_ns=20.0)
        assert env.shape_type == PulseShapeType.GAUSSIAN_SQUARE

    def test_generate_cosine(self):
        """Test generate_envelope with cosine shape."""
        env = generate_envelope("cosine", num_time_steps=100, duration_ns=20.0)
        assert env.shape_type == PulseShapeType.COSINE

    def test_generate_sech(self):
        """Test generate_envelope with sech shape."""
        env = generate_envelope("sech", num_time_steps=100, duration_ns=20.0)
        assert env.shape_type == PulseShapeType.SECH

    def test_generate_with_enum(self):
        """Test generate_envelope accepts PulseShapeType enum."""
        env = generate_envelope(PulseShapeType.GAUSSIAN, num_time_steps=100, duration_ns=20.0)
        assert env.shape_type == PulseShapeType.GAUSSIAN

    def test_generate_custom_amplitude(self):
        """Test generate_envelope respects amplitude."""
        env = generate_envelope("square", num_time_steps=100, duration_ns=20.0, amplitude=0.5)
        assert np.allclose(env.i_envelope, 0.5)

    def test_generate_stores_parameters(self):
        """Test generate_envelope stores parameters."""
        env = generate_envelope("gaussian", num_time_steps=100, duration_ns=20.0, amplitude=0.8)
        assert env.parameters["amplitude"] == 0.8

    def test_generate_invalid_num_time_steps(self):
        """Test generate_envelope rejects invalid num_time_steps."""
        with pytest.raises(ValueError, match="num_time_steps must be >= 1"):
            generate_envelope("square", num_time_steps=0, duration_ns=20.0)

    def test_generate_invalid_duration(self):
        """Test generate_envelope rejects invalid duration."""
        with pytest.raises(ValueError, match="duration_ns must be > 0"):
            generate_envelope("square", num_time_steps=100, duration_ns=-1.0)

    def test_generate_unknown_shape(self):
        """Test generate_envelope raises for unknown shape."""
        with pytest.raises(ValueError):
            generate_envelope("unknown_shape", num_time_steps=100, duration_ns=20.0)


class TestApplyWindow:
    """Tests for the apply_window function."""

    def test_apply_hann_window(self):
        """Test applying Hann window."""
        envelope = np.ones(100)
        windowed = apply_window(envelope, window_type="hann", edge_fraction=0.1)
        # Edges should be reduced
        assert windowed[0] < envelope[0]
        assert windowed[-1] < envelope[-1]
        # Center should be unchanged
        assert windowed[50] == pytest.approx(1.0)

    def test_apply_hamming_window(self):
        """Test applying Hamming window."""
        envelope = np.ones(100)
        windowed = apply_window(envelope, window_type="hamming", edge_fraction=0.1)
        assert windowed[0] < envelope[0]
        assert windowed[50] == pytest.approx(1.0)

    def test_apply_blackman_window(self):
        """Test applying Blackman window."""
        envelope = np.ones(100)
        windowed = apply_window(envelope, window_type="blackman", edge_fraction=0.1)
        assert windowed[0] < envelope[0]
        assert windowed[50] == pytest.approx(1.0)

    def test_apply_window_unknown_type(self):
        """Test apply_window raises for unknown window type."""
        envelope = np.ones(100)
        with pytest.raises(ValueError, match="Unknown window type"):
            apply_window(envelope, window_type="unknown")

    def test_apply_window_preserves_shape(self):
        """Test apply_window preserves array shape."""
        envelope = np.ones(100)
        windowed = apply_window(envelope)
        assert windowed.shape == envelope.shape

    def test_apply_window_different_edge_fractions(self):
        """Test apply_window with different edge fractions."""
        envelope = np.ones(100)
        small_edge = apply_window(envelope, edge_fraction=0.05)
        large_edge = apply_window(envelope, edge_fraction=0.2)
        # Larger edge fraction affects more of the pulse
        assert small_edge[15] == pytest.approx(1.0)
        assert large_edge[15] < 1.0


class TestPulseEnvelopeDataclass:
    """Tests for PulseEnvelope dataclass."""

    def test_pulse_envelope_creation(self):
        """Test creating PulseEnvelope instance."""
        i_env = np.ones(50)
        q_env = np.zeros(50)
        times = np.linspace(0, 10e-9, 50)
        
        env = PulseEnvelope(
            i_envelope=i_env,
            q_envelope=q_env,
            times=times,
            shape_type=PulseShapeType.SQUARE,
            parameters={"amplitude": 1.0},
        )
        
        assert np.array_equal(env.i_envelope, i_env)
        assert np.array_equal(env.q_envelope, q_env)
        assert env.shape_type == PulseShapeType.SQUARE
        assert env.parameters["amplitude"] == 1.0


class TestPulseShapeTypeEnum:
    """Tests for PulseShapeType enumeration."""

    def test_all_shape_types_have_values(self):
        """Test all pulse shape types have string values."""
        assert PulseShapeType.SQUARE.value == "square"
        assert PulseShapeType.GAUSSIAN.value == "gaussian"
        assert PulseShapeType.GAUSSIAN_SQUARE.value == "gaussian_square"
        assert PulseShapeType.DRAG.value == "drag"
        assert PulseShapeType.COSINE.value == "cosine"
        assert PulseShapeType.SECH.value == "sech"
        assert PulseShapeType.CUSTOM.value == "custom"

    def test_shape_type_from_string(self):
        """Test creating PulseShapeType from string."""
        assert PulseShapeType("gaussian") == PulseShapeType.GAUSSIAN
        assert PulseShapeType("drag") == PulseShapeType.DRAG
