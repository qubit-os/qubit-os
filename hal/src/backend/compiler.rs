// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! Pulse-to-native-gate compilation trait.
//!
//! Defines how optimized pulses are mapped to the native gate set
//! of a specific quantum backend. Each backend has a finite set of
//! physically implemented gates (e.g., IQM uses CZ + single-qubit,
//! IBM uses ECR + single-qubit, IonQ uses MS + single-qubit).
//!
//! The compilation step bridges the gap between GRAPE-optimized
//! arbitrary unitaries and hardware-executable gate sequences.
//!
//! Reference: Cross et al., "OpenQASM 3: A broader and deeper quantum
//!   assembly language", ACM Transactions on Quantum Computing (2022).

use std::fmt;

use crate::error::BackendError;

/// A native gate that a backend can physically execute.
#[derive(Debug, Clone, PartialEq)]
pub struct NativeGate {
    /// Gate name (e.g., "cz", "ecr", "rx", "rz").
    pub name: String,

    /// Target qubit indices.
    pub qubits: Vec<u32>,

    /// Gate parameters (e.g., rotation angle for Rx, Rz).
    pub parameters: Vec<f64>,

    /// Estimated gate duration in nanoseconds.
    pub duration_ns: f64,

    /// Estimated gate infidelity (1 - fidelity).
    pub infidelity: f64,
}

impl fmt::Display for NativeGate {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        if self.parameters.is_empty() {
            write!(f, "{}(q{})", self.name, format_qubits(&self.qubits))
        } else {
            let params: Vec<String> =
                self.parameters.iter().map(|p| format!("{:.4}", p)).collect();
            write!(
                f,
                "{}({}) q{}",
                self.name,
                params.join(", "),
                format_qubits(&self.qubits)
            )
        }
    }
}

fn format_qubits(qubits: &[u32]) -> String {
    qubits
        .iter()
        .map(|q| q.to_string())
        .collect::<Vec<_>>()
        .join(", q")
}

/// Result of compiling a pulse to native gates.
#[derive(Debug, Clone)]
pub struct CompiledSequence {
    /// Ordered sequence of native gates.
    pub gates: Vec<NativeGate>,

    /// Total estimated duration in nanoseconds.
    pub total_duration_ns: f64,

    /// Total estimated infidelity (sum of gate infidelities).
    pub total_infidelity: f64,

    /// Backend name that produced this compilation.
    pub backend: String,
}

impl CompiledSequence {
    /// Estimated fidelity of the full sequence.
    pub fn estimated_fidelity(&self) -> f64 {
        // Product of individual gate fidelities
        self.gates
            .iter()
            .map(|g| 1.0 - g.infidelity)
            .product()
    }
}

/// Trait for compiling optimized pulses to backend-native gate sequences.
///
/// Each backend implements this trait to define:
/// 1. What gates it can physically execute (native basis)
/// 2. How to decompose arbitrary unitaries into that basis
pub trait NativeGateCompiler: Send + Sync {
    /// Return the native gate set for this backend.
    ///
    /// These are the gates the hardware can physically execute.
    fn native_basis(&self) -> Vec<String>;

    /// Compile a target unitary into native gates.
    ///
    /// # Arguments
    /// * `unitary` - Flat row-major complex128 array of the target unitary
    /// * `dim` - Dimension of the unitary (2^num_qubits)
    /// * `qubit_indices` - Physical qubit indices for the gate
    fn compile_unitary(
        &self,
        unitary: &[f64],
        dim: usize,
        qubit_indices: &[u32],
    ) -> Result<CompiledSequence, BackendError>;
}

/// Default single-qubit decomposition into Rz-Rx-Rz (Euler angles).
///
/// Any single-qubit unitary can be written as:
///   U = e^{iα} Rz(β) Rx(γ) Rz(δ)
///
/// Reference: Nielsen & Chuang, "Quantum Computation and Quantum
///   Information", Theorem 4.1 (2010).
pub fn decompose_single_qubit_zxz(
    unitary_flat: &[f64],
    qubit: u32,
    gate_duration_ns: f64,
    gate_infidelity: f64,
) -> Result<Vec<NativeGate>, BackendError> {
    if unitary_flat.len() != 8 {
        return Err(BackendError::InvalidRequest(format!(
            "Expected 8 floats (2x2 complex), got {}",
            unitary_flat.len()
        )));
    }

    // Parse complex 2x2 matrix: [re(00), im(00), re(01), im(01), re(10), im(10), re(11), im(11)]
    let u00_re = unitary_flat[0];
    let u00_im = unitary_flat[1];
    let u01_re = unitary_flat[2];
    let u01_im = unitary_flat[3];

    let u00_mag = (u00_re * u00_re + u00_im * u00_im).sqrt();
    let u01_mag = (u01_re * u01_re + u01_im * u01_im).sqrt();

    // γ = 2 * acos(|u00|)
    let gamma = 2.0 * u00_mag.min(1.0).acos();

    // β and δ from phases of u00 and u01
    // When magnitude is ~0, the phase is undefined — use 0.0
    let phase_00 = if u00_mag > 1e-12 {
        u00_im.atan2(u00_re)
    } else {
        0.0
    };
    let phase_01 = if u01_mag > 1e-12 {
        u01_im.atan2(-u01_re)
    } else {
        0.0
    };
    let beta = phase_00 - phase_01;
    let delta = phase_00 + phase_01;

    let mut gates = Vec::new();

    // Only emit gates with non-trivial angles
    if delta.abs() > 1e-10 {
        gates.push(NativeGate {
            name: "rz".to_string(),
            qubits: vec![qubit],
            parameters: vec![delta],
            duration_ns: gate_duration_ns,
            infidelity: gate_infidelity,
        });
    }

    if gamma.abs() > 1e-10 {
        gates.push(NativeGate {
            name: "rx".to_string(),
            qubits: vec![qubit],
            parameters: vec![gamma],
            duration_ns: gate_duration_ns,
            infidelity: gate_infidelity,
        });
    }

    if beta.abs() > 1e-10 {
        gates.push(NativeGate {
            name: "rz".to_string(),
            qubits: vec![qubit],
            parameters: vec![beta],
            duration_ns: gate_duration_ns,
            infidelity: gate_infidelity,
        });
    }

    Ok(gates)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::f64::consts::PI;

    #[test]
    fn test_native_gate_display_no_params() {
        let gate = NativeGate {
            name: "cz".to_string(),
            qubits: vec![0, 1],
            parameters: vec![],
            duration_ns: 200.0,
            infidelity: 0.01,
        };
        assert_eq!(gate.to_string(), "cz(q0, q1)");
    }

    #[test]
    fn test_native_gate_display_with_params() {
        let gate = NativeGate {
            name: "rx".to_string(),
            qubits: vec![0],
            parameters: vec![PI / 2.0],
            duration_ns: 20.0,
            infidelity: 0.001,
        };
        let display = gate.to_string();
        assert!(display.contains("rx("));
        assert!(display.contains("q0"));
    }

    #[test]
    fn test_compiled_sequence_fidelity() {
        let seq = CompiledSequence {
            gates: vec![
                NativeGate {
                    name: "rz".into(),
                    qubits: vec![0],
                    parameters: vec![1.0],
                    duration_ns: 0.0,  // Virtual Z gate
                    infidelity: 0.0,
                },
                NativeGate {
                    name: "rx".into(),
                    qubits: vec![0],
                    parameters: vec![PI],
                    duration_ns: 20.0,
                    infidelity: 0.001,
                },
            ],
            total_duration_ns: 20.0,
            total_infidelity: 0.001,
            backend: "test".into(),
        };
        // (1.0) * (1.0 - 0.001) = 0.999
        assert!((seq.estimated_fidelity() - 0.999).abs() < 1e-10);
    }

    #[test]
    fn test_decompose_identity() {
        // Identity: [[1,0,0,0], [0,0,1,0], [0,0,0,0], [0,0,1,0]]
        // Wait, flat format: re(00),im(00),re(01),im(01),re(10),im(10),re(11),im(11)
        let identity = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0];
        let gates = decompose_single_qubit_zxz(&identity, 0, 20.0, 0.001).unwrap();
        // Identity should produce no gates (all angles ~0)
        assert!(gates.is_empty(), "Identity decomposed to {} gates", gates.len());
    }

    #[test]
    fn test_decompose_x_gate() {
        // X gate: [[0,0,1,0], [1,0,0,0]]
        // Flat: re(00)=0,im(00)=0,re(01)=1,im(01)=0,re(10)=1,im(10)=0,re(11)=0,im(11)=0
        let x_gate = [0.0, 0.0, 1.0, 0.0, 1.0, 0.0, 0.0, 0.0];
        let gates = decompose_single_qubit_zxz(&x_gate, 0, 20.0, 0.001).unwrap();
        // Should produce at least an Rx(π) gate
        assert!(!gates.is_empty());
        let has_rx = gates.iter().any(|g| g.name == "rx");
        assert!(has_rx, "X gate should decompose with Rx");
    }

    #[test]
    fn test_decompose_invalid_size() {
        let bad = [1.0, 0.0, 0.0];
        let result = decompose_single_qubit_zxz(&bad, 0, 20.0, 0.001);
        assert!(result.is_err());
    }
}
