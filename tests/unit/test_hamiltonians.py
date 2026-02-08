"""Tests for hamiltonians module.

Tests for Pauli matrices, standard gates, tensor products, Pauli string parsing,
Hamiltonian building, rotation gates, and gate embedding.

NOTE: There is a convention difference in the codebase:
- pauli_string_to_matrix uses big-endian: qubit 0 = leftmost in tensor product
- embed_gate uses little-endian: qubit 0 = rightmost (LSB) in tensor product
Tests document the actual behavior.
"""

import numpy as np
import pytest

from qubitos.pulsegen.hamiltonians import (
    PAULI_I,
    PAULI_MATRICES,
    PAULI_X,
    PAULI_Y,
    PAULI_Z,
    STANDARD_GATES,
    build_hamiltonian,
    embed_gate,
    get_target_unitary,
    parse_pauli_string,
    pauli_string_to_matrix,
    rotation_gate,
    tensor_product,
)

# Convenience aliases
GATE_X = STANDARD_GATES["X"]
GATE_Y = STANDARD_GATES["Y"]
GATE_Z = STANDARD_GATES["Z"]
GATE_H = STANDARD_GATES["H"]
GATE_S = STANDARD_GATES["S"]
GATE_T = STANDARD_GATES["T"]
GATE_CZ = STANDARD_GATES["CZ"]
GATE_CNOT = STANDARD_GATES["CNOT"]
GATE_SWAP = STANDARD_GATES["SWAP"]


class TestPauliMatrices:
    """Tests for Pauli matrix definitions."""

    def test_pauli_i_is_identity(self):
        """Test Pauli I is the identity matrix."""
        assert np.allclose(PAULI_I, np.eye(2))

    def test_pauli_x_is_correct(self):
        """Test Pauli X has correct form."""
        expected = np.array([[0, 1], [1, 0]], dtype=np.complex128)
        assert np.allclose(PAULI_X, expected)

    def test_pauli_y_is_correct(self):
        """Test Pauli Y has correct form."""
        expected = np.array([[0, -1j], [1j, 0]], dtype=np.complex128)
        assert np.allclose(PAULI_Y, expected)

    def test_pauli_z_is_correct(self):
        """Test Pauli Z has correct form."""
        expected = np.array([[1, 0], [0, -1]], dtype=np.complex128)
        assert np.allclose(PAULI_Z, expected)

    def test_paulis_are_hermitian(self):
        """Test all Pauli matrices are Hermitian."""
        for name, P in PAULI_MATRICES.items():
            assert np.allclose(P, P.conj().T), f"{name} is not Hermitian"

    def test_paulis_are_unitary(self):
        """Test all Pauli matrices are unitary."""
        for name, P in PAULI_MATRICES.items():
            assert np.allclose(P @ P.conj().T, np.eye(2)), f"{name} is not unitary"

    def test_pauli_squares_to_identity(self):
        """Test P^2 = I for all Pauli matrices."""
        for name, P in PAULI_MATRICES.items():
            assert np.allclose(P @ P, np.eye(2)), f"{name}^2 != I"


class TestStandardGates:
    """Tests for standard gate definitions."""

    def test_single_qubit_gates_are_unitary(self):
        """Test single-qubit gates are unitary."""
        single_qubit = ["X", "Y", "Z", "H", "S", "T", "SX"]
        for name in single_qubit:
            G = STANDARD_GATES[name]
            assert np.allclose(
                G @ G.conj().T, np.eye(2)
            ), f"{name} is not unitary"

    def test_two_qubit_gates_are_unitary(self):
        """Test two-qubit gates are unitary."""
        two_qubit = ["CZ", "CNOT", "SWAP", "ISWAP"]
        for name in two_qubit:
            G = STANDARD_GATES[name]
            assert np.allclose(
                G @ G.conj().T, np.eye(4)
            ), f"{name} is not unitary"

    def test_hadamard_creates_superposition(self):
        """Test Hadamard creates equal superposition from |0>."""
        zero_state = np.array([1, 0], dtype=np.complex128)
        plus_state = GATE_H @ zero_state
        expected = np.array([1, 1], dtype=np.complex128) / np.sqrt(2)
        assert np.allclose(plus_state, expected)

    def test_cnot_flips_target_when_control_is_one(self):
        """Test CNOT flips target qubit when control is |1>."""
        # |10> -> |11>
        state_10 = np.array([0, 0, 1, 0], dtype=np.complex128)
        result = GATE_CNOT @ state_10
        expected = np.array([0, 0, 0, 1], dtype=np.complex128)
        assert np.allclose(result, expected)

    def test_cz_adds_phase_to_11(self):
        """Test CZ adds -1 phase to |11> state."""
        state_11 = np.array([0, 0, 0, 1], dtype=np.complex128)
        result = GATE_CZ @ state_11
        expected = np.array([0, 0, 0, -1], dtype=np.complex128)
        assert np.allclose(result, expected)

    def test_standard_gates_dict_complete(self):
        """Test standard gates dictionary has expected gates."""
        expected_gates = [
            "I", "X", "Y", "Z", "H", "S", "T", "SX",
            "CZ", "CNOT", "SWAP", "ISWAP"
        ]
        for gate in expected_gates:
            assert gate in STANDARD_GATES, f"{gate} missing from STANDARD_GATES"


class TestTensorProduct:
    """Tests for tensor_product function."""

    def test_tensor_product_two_paulis(self):
        """Test tensor product of two Pauli matrices."""
        result = tensor_product([PAULI_X, PAULI_Z])
        expected = np.kron(PAULI_X, PAULI_Z)
        assert np.allclose(result, expected)

    def test_tensor_product_three_operators(self):
        """Test tensor product of three operators."""
        result = tensor_product([PAULI_X, PAULI_Y, PAULI_Z])
        expected = np.kron(np.kron(PAULI_X, PAULI_Y), PAULI_Z)
        assert np.allclose(result, expected)

    def test_tensor_product_single_operator(self):
        """Test tensor product of single operator returns it unchanged."""
        result = tensor_product([PAULI_X])
        assert np.allclose(result, PAULI_X)

    def test_tensor_product_identities(self):
        """Test tensor product of identities is larger identity."""
        result = tensor_product([PAULI_I, PAULI_I])
        assert np.allclose(result, np.eye(4))

    def test_tensor_product_empty_list_raises(self):
        """Test that empty list raises ValueError."""
        with pytest.raises(ValueError, match="at least one operator"):
            tensor_product([])


class TestPauliStringToMatrix:
    """Tests for pauli_string_to_matrix function.
    
    Uses big-endian convention: qubit 0 = leftmost position in tensor product.
    """

    def test_single_pauli(self):
        """Test single Pauli operator in 1-qubit system."""
        result = pauli_string_to_matrix("X0", num_qubits=1)
        assert np.allclose(result, PAULI_X)

    def test_single_pauli_two_qubit_system(self):
        """Test single Pauli X on qubit 0 in 2-qubit system.
        
        Big-endian: qubit 0 = leftmost, so X0 = X ⊗ I
        """
        result = pauli_string_to_matrix("X0", num_qubits=2)
        expected = np.kron(PAULI_X, PAULI_I)
        assert np.allclose(result, expected)

    def test_single_pauli_on_second_qubit(self):
        """Test single Pauli X on qubit 1 in 2-qubit system.
        
        Big-endian: qubit 1 = rightmost, so X1 = I ⊗ X
        """
        result = pauli_string_to_matrix("X1", num_qubits=2)
        expected = np.kron(PAULI_I, PAULI_X)
        assert np.allclose(result, expected)

    def test_two_paulis(self):
        """Test two Pauli operators."""
        result = pauli_string_to_matrix("X0 Z1", num_qubits=2)
        # Big-endian: X0 Z1 = X ⊗ Z (qubit 0 left, qubit 1 right)
        expected = np.kron(PAULI_X, PAULI_Z)
        assert np.allclose(result, expected)

    def test_all_paulis(self):
        """Test string with all four Pauli types."""
        result = pauli_string_to_matrix("I0 X1 Y2 Z3", num_qubits=4)
        # Big-endian: I0 X1 Y2 Z3 = I ⊗ X ⊗ Y ⊗ Z
        expected = np.kron(np.kron(np.kron(PAULI_I, PAULI_X), PAULI_Y), PAULI_Z)
        assert np.allclose(result, expected)

    def test_identity_on_empty_qubits(self):
        """Test identity is applied to unspecified qubits."""
        result = pauli_string_to_matrix("X0", num_qubits=3)
        # Big-endian: X on qubit 0, identity on 1 and 2
        # X0 = X ⊗ I ⊗ I
        expected = np.kron(np.kron(PAULI_X, PAULI_I), PAULI_I)
        assert np.allclose(result, expected)

    def test_invalid_qubit_index_raises(self):
        """Test invalid qubit index raises error."""
        with pytest.raises((ValueError, IndexError)):
            pauli_string_to_matrix("X5", num_qubits=2)

    def test_case_insensitive(self):
        """Test Pauli names are case insensitive."""
        result_lower = pauli_string_to_matrix("x0", num_qubits=1)
        result_upper = pauli_string_to_matrix("X0", num_qubits=1)
        assert np.allclose(result_lower, result_upper)


class TestParsePauliString:
    """Tests for parse_pauli_string function.
    
    Uses big-endian convention: qubit 0 = leftmost position in tensor product.
    """

    def test_single_term(self):
        """Test parsing single term."""
        H = parse_pauli_string("1.0 * X0", num_qubits=1)
        assert np.allclose(H, PAULI_X)

    def test_coefficient(self):
        """Test coefficient is applied."""
        H = parse_pauli_string("0.5 * X0", num_qubits=1)
        assert np.allclose(H, 0.5 * PAULI_X)

    def test_sum_of_terms(self):
        """Test sum of multiple terms."""
        H = parse_pauli_string("1.0 * X0 + 1.0 * Z0", num_qubits=1)
        expected = PAULI_X + PAULI_Z
        assert np.allclose(H, expected)

    def test_subtraction(self):
        """Test subtraction in expression using negative coefficient.
        
        The parser handles subtraction by converting '-' to '+-', so we use
        the explicit negative coefficient form.
        """
        H = parse_pauli_string("1.0 * X0 + -0.5 * Z0", num_qubits=1)
        expected = PAULI_X - 0.5 * PAULI_Z
        assert np.allclose(H, expected)

    def test_two_qubit_term(self):
        """Test two-qubit Pauli string."""
        H = parse_pauli_string("1.0 * X0 Z1", num_qubits=2)
        # Big-endian: X0 Z1 = X ⊗ Z
        expected = np.kron(PAULI_X, PAULI_Z)
        assert np.allclose(H, expected)

    def test_no_coefficient(self):
        """Test term without explicit coefficient (defaults to 1.0)."""
        H = parse_pauli_string("X0 + Z0", num_qubits=1)
        expected = PAULI_X + PAULI_Z
        assert np.allclose(H, expected)

    def test_complex_expression(self):
        """Test complex multi-term expression."""
        H = parse_pauli_string("0.5 * X0 + 0.3 * Z0 Z1 + -0.2 * Y1", num_qubits=2)
        # Big-endian convention
        expected = (
            0.5 * np.kron(PAULI_X, PAULI_I)  # X0 = X ⊗ I
            + 0.3 * np.kron(PAULI_Z, PAULI_Z)  # Z0 Z1 = Z ⊗ Z
            - 0.2 * np.kron(PAULI_I, PAULI_Y)  # Y1 = I ⊗ Y
        )
        assert np.allclose(H, expected)

    def test_result_is_hermitian(self):
        """Test parsed Hamiltonian is Hermitian."""
        H = parse_pauli_string("1.0 * X0 + 0.5 * Z0 Z1 + 0.3 * Y1", num_qubits=2)
        assert np.allclose(H, H.conj().T)


class TestBuildHamiltonian:
    """Tests for build_hamiltonian function."""

    def test_default_no_drift(self):
        """Test default with no drift Hamiltonian."""
        H0, Hc = build_hamiltonian(num_qubits=1)
        assert np.allclose(H0, 0)
        assert len(Hc) == 2  # X and Y controls

    def test_drift_string(self):
        """Test drift Hamiltonian from string."""
        H0, Hc = build_hamiltonian(drift="0.5 * Z0", num_qubits=1)
        assert np.allclose(H0, 0.5 * PAULI_Z)

    def test_drift_matrix(self):
        """Test drift Hamiltonian from matrix."""
        drift = 0.5 * PAULI_Z
        H0, Hc = build_hamiltonian(drift=drift, num_qubits=1)
        assert np.allclose(H0, drift)

    def test_controls_string(self):
        """Test control Hamiltonians from strings."""
        H0, Hc = build_hamiltonian(controls=["X0", "Y0"], num_qubits=1)
        assert len(Hc) == 2
        assert np.allclose(Hc[0], PAULI_X)
        assert np.allclose(Hc[1], PAULI_Y)

    def test_controls_matrix(self):
        """Test control Hamiltonians from matrices."""
        controls = [PAULI_X, PAULI_Y]
        H0, Hc = build_hamiltonian(controls=controls, num_qubits=1)
        assert len(Hc) == 2
        assert np.allclose(Hc[0], PAULI_X)

    def test_two_qubit_default_controls(self):
        """Test default controls for two-qubit system."""
        H0, Hc = build_hamiltonian(num_qubits=2)
        # Should have X0, Y0, X1, Y1
        assert len(Hc) == 4


class TestRotationGate:
    """Tests for rotation_gate function."""

    def test_rx_pi_equals_x(self):
        """Test RX(pi) is equivalent to X gate (up to global phase)."""
        rx_pi = rotation_gate("X", np.pi)
        # RX(pi) = -i*X, so |RX(pi)| = |X|
        assert np.allclose(np.abs(rx_pi), np.abs(PAULI_X))

    def test_ry_pi_equals_y(self):
        """Test RY(pi) is equivalent to Y gate (up to global phase)."""
        ry_pi = rotation_gate("Y", np.pi)
        assert np.allclose(np.abs(ry_pi), np.abs(PAULI_Y))

    def test_rz_pi_equals_z(self):
        """Test RZ(pi) is equivalent to Z gate (up to global phase)."""
        rz_pi = rotation_gate("Z", np.pi)
        assert np.allclose(np.abs(rz_pi), np.abs(PAULI_Z))

    def test_rotation_zero_is_identity(self):
        """Test rotation by 0 is identity."""
        for axis in ["X", "Y", "Z"]:
            r = rotation_gate(axis, 0)
            assert np.allclose(r, np.eye(2))

    def test_rotation_is_unitary(self):
        """Test rotation gates are unitary."""
        for axis in ["X", "Y", "Z"]:
            for angle in [np.pi / 4, np.pi / 2, np.pi]:
                r = rotation_gate(axis, angle)
                assert np.allclose(r @ r.conj().T, np.eye(2))

    def test_invalid_axis_raises(self):
        """Test invalid axis raises error."""
        with pytest.raises(ValueError, match="Unknown rotation axis"):
            rotation_gate("W", np.pi)

    def test_case_insensitive(self):
        """Test axis is case insensitive."""
        rx_upper = rotation_gate("X", np.pi / 2)
        rx_lower = rotation_gate("x", np.pi / 2)
        assert np.allclose(rx_upper, rx_lower)


class TestGetTargetUnitary:
    """Tests for get_target_unitary function."""

    def test_single_qubit_gate(self):
        """Test getting single-qubit gate."""
        X = get_target_unitary("X", num_qubits=1)
        assert np.allclose(X, GATE_X)

    def test_hadamard(self):
        """Test getting Hadamard gate."""
        H = get_target_unitary("H", num_qubits=1)
        assert np.allclose(H, GATE_H)

    def test_two_qubit_gate(self):
        """Test getting two-qubit gate."""
        CZ = get_target_unitary("CZ", num_qubits=2)
        assert np.allclose(CZ, GATE_CZ)

    def test_rotation_gate(self):
        """Test getting rotation gate with angle."""
        RX = get_target_unitary("RX", num_qubits=1, angle=np.pi / 2)
        expected = rotation_gate("X", np.pi / 2)
        assert np.allclose(RX, expected)

    def test_rotation_requires_angle(self):
        """Test rotation gate requires angle parameter."""
        with pytest.raises(ValueError, match="requires an angle"):
            get_target_unitary("RX", num_qubits=1)

    def test_unknown_gate_raises(self):
        """Test unknown gate raises error."""
        with pytest.raises(ValueError, match="Unknown gate"):
            get_target_unitary("UNKNOWN", num_qubits=1)

    def test_gate_embedding(self):
        """Test gate is embedded in larger system.
        
        Uses little-endian convention: qubit 0 = rightmost (LSB).
        """
        X = get_target_unitary("X", num_qubits=2, qubit_indices=[0])
        # Little-endian: qubit 0 is rightmost, so X on qubit 0 = I ⊗ X
        expected = np.kron(PAULI_I, PAULI_X)
        assert np.allclose(X, expected)

    def test_gate_on_second_qubit(self):
        """Test gate on second qubit of two-qubit system.
        
        Little-endian: qubit 1 = leftmost.
        """
        X = get_target_unitary("X", num_qubits=2, qubit_indices=[1])
        # Little-endian: qubit 1 is leftmost, so X on qubit 1 = X ⊗ I
        expected = np.kron(PAULI_X, PAULI_I)
        assert np.allclose(X, expected)

    def test_wrong_qubit_indices_raises(self):
        """Test wrong number of qubit indices raises error."""
        with pytest.raises(ValueError, match="acts on 2 qubits"):
            get_target_unitary("CZ", num_qubits=3, qubit_indices=[0])

    def test_case_insensitive(self):
        """Test gate name is case insensitive."""
        x_lower = get_target_unitary("x", num_qubits=1)
        x_upper = get_target_unitary("X", num_qubits=1)
        assert np.allclose(x_lower, x_upper)


class TestEmbedGate:
    """Tests for embed_gate function.
    
    Uses little-endian convention: qubit 0 = rightmost (LSB) position.
    """

    def test_embed_in_same_size(self):
        """Test embedding gate in same-size system returns gate."""
        X_embedded = embed_gate(PAULI_X, num_qubits=1, qubit_indices=[0])
        assert np.allclose(X_embedded, PAULI_X)

    def test_embed_on_first_qubit(self):
        """Test embedding on first qubit (qubit 0 = rightmost)."""
        X_embedded = embed_gate(PAULI_X, num_qubits=2, qubit_indices=[0])
        # Little-endian: qubit 0 is rightmost, so X on qubit 0 = I ⊗ X
        expected = np.kron(PAULI_I, PAULI_X)
        assert np.allclose(X_embedded, expected)

    def test_embed_on_second_qubit(self):
        """Test embedding on second qubit (qubit 1 = leftmost)."""
        X_embedded = embed_gate(PAULI_X, num_qubits=2, qubit_indices=[1])
        # Little-endian: qubit 1 is leftmost, so X on qubit 1 = X ⊗ I
        expected = np.kron(PAULI_X, PAULI_I)
        assert np.allclose(X_embedded, expected)

    def test_embed_two_qubit_gate(self):
        """Test embedding two-qubit gate."""
        CZ_embedded = embed_gate(GATE_CZ, num_qubits=3, qubit_indices=[0, 2])
        # Should be a 8x8 matrix
        assert CZ_embedded.shape == (8, 8)
        # Should be unitary
        assert np.allclose(CZ_embedded @ CZ_embedded.conj().T, np.eye(8))

    def test_embedded_gate_is_unitary(self):
        """Test embedded gates are unitary."""
        for gate in [PAULI_X, PAULI_Y, PAULI_Z, GATE_H]:
            for qubit_idx in [0, 1, 2]:
                embedded = embed_gate(gate, num_qubits=3, qubit_indices=[qubit_idx])
                assert np.allclose(embedded @ embedded.conj().T, np.eye(8))

    def test_embed_on_non_adjacent_qubits(self):
        """Test embedding two-qubit gate on non-adjacent qubits."""
        # CNOT on qubits 0 and 2 of a 3-qubit system
        CNOT_embedded = embed_gate(GATE_CNOT, num_qubits=3, qubit_indices=[0, 2])
        assert CNOT_embedded.shape == (8, 8)
        assert np.allclose(CNOT_embedded @ CNOT_embedded.conj().T, np.eye(8))
