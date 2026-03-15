// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! QuTiP simulator backend using PyO3.
//!
//! This backend provides quantum simulation using QuTiP (Quantum Toolbox in Python)
//! via PyO3 for Python interop. It runs a local QuTiP simulation to execute pulse
//! sequences and return measurement results.
//!
//! # Requirements
//!
//! - Python 3.9+ with QuTiP installed
//! - NumPy
//!
//! # Architecture
//!
//! The backend embeds Python and executes QuTiP code to:
//! 1. Build the time-dependent Hamiltonian from pulse envelopes
//! 2. Run mesolve() for time evolution
//! 3. Compute measurement probabilities
//! 4. Sample measurement outcomes
//!
//! # Security
//!
//! - Python execution is wrapped with a timeout to prevent infinite hangs
//! - Default timeout is 300 seconds, configurable via ServerConfig

use async_trait::async_trait;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use std::collections::HashMap;
use std::ffi::CString;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;
use tracing::{debug, error, info, warn};

use super::{BackendType, QuantumBackend};
use crate::config::{QutipConfig, ResourceLimits};
use crate::error::BackendError;

use super::r#trait::{
    ExecutePulseRequest, HardwareInfo, HealthStatus, MeasurementResult, ResultQuality,
};

/// Default timeout for Python execution in seconds.
const DEFAULT_PYTHON_TIMEOUT_SECS: u64 = 300;

/// Static flag to track if Python/QuTiP is available
static QUTIP_AVAILABLE: AtomicBool = AtomicBool::new(false);
static QUTIP_CHECKED: AtomicBool = AtomicBool::new(false);

/// QuTiP simulator backend.
pub struct QutipBackend {
    /// Backend name
    name: String,

    /// Number of qubits
    num_qubits: u32,

    /// Resource limits
    limits: ResourceLimits,

    /// Whether to return state vectors
    supports_state_vector: bool,

    /// Timeout for Python execution
    timeout: Duration,
}

impl QutipBackend {
    /// Create a new QuTiP backend.
    pub fn new(config: &QutipConfig) -> Result<Self, BackendError> {
        // Check if QuTiP is available
        if !Self::check_qutip_available() {
            return Err(BackendError::Unavailable(
                "QuTiP is not available. Install with: pip install qutip numpy".to_string(),
            ));
        }

        info!(num_qubits = config.num_qubits, "Initializing QuTiP backend");

        Ok(Self {
            name: "qutip_simulator".to_string(),
            num_qubits: config.num_qubits,
            limits: ResourceLimits {
                max_qubits: config.num_qubits,
                max_shots: config.max_shots,
                ..Default::default()
            },
            supports_state_vector: true,
            timeout: Duration::from_secs(DEFAULT_PYTHON_TIMEOUT_SECS),
        })
    }

    /// Create with default configuration.
    pub fn new_default() -> Result<Self, BackendError> {
        Self::new(&QutipConfig::default())
    }

    /// Set execution timeout.
    pub fn with_timeout(mut self, timeout: Duration) -> Self {
        self.timeout = timeout;
        self
    }

    /// Check if QuTiP is available.
    pub fn check_qutip_available() -> bool {
        // Only check once
        if QUTIP_CHECKED.load(Ordering::Relaxed) {
            return QUTIP_AVAILABLE.load(Ordering::Relaxed);
        }

        let available = Python::with_gil(|py| {
            // Try to import qutip
            match py.import("qutip") {
                Ok(_) => {
                    // Also check numpy
                    match py.import("numpy") {
                        Ok(_) => {
                            info!("QuTiP and NumPy are available");
                            true
                        }
                        Err(e) => {
                            warn!("NumPy not available: {}", e);
                            false
                        }
                    }
                }
                Err(e) => {
                    warn!("QuTiP not available: {}", e);
                    false
                }
            }
        });

        QUTIP_CHECKED.store(true, Ordering::Relaxed);
        QUTIP_AVAILABLE.store(available, Ordering::Relaxed);
        available
    }

    /// Execute pulse simulation in Python.
    fn execute_python(
        &self,
        request: &ExecutePulseRequest,
    ) -> Result<MeasurementResult, BackendError> {
        Python::with_gil(|py| self.execute_python_inner(py, request))
    }

    fn execute_python_inner(
        &self,
        py: Python<'_>,
        request: &ExecutePulseRequest,
    ) -> Result<MeasurementResult, BackendError> {
        // Import required modules
        let qutip = py
            .import("qutip")
            .map_err(|e| BackendError::Python(format!("Failed to import qutip: {}", e)))?;
        let numpy = py
            .import("numpy")
            .map_err(|e| BackendError::Python(format!("Failed to import numpy: {}", e)))?;

        // Convert envelopes to numpy arrays (PyO3 0.25: PyList::new returns Result)
        let i_env = PyList::new(py, &request.i_envelope).map_err(|e| {
            BackendError::Python(format!("Failed to create I envelope list: {}", e))
        })?;
        let q_env = PyList::new(py, &request.q_envelope).map_err(|e| {
            BackendError::Python(format!("Failed to create Q envelope list: {}", e))
        })?;

        let i_array = numpy
            .call_method1("array", (&i_env,))
            .map_err(|e| BackendError::Python(format!("Failed to create I numpy array: {}", e)))?;
        let q_array = numpy
            .call_method1("array", (&q_env,))
            .map_err(|e| BackendError::Python(format!("Failed to create Q numpy array: {}", e)))?;

        // Build the simulation context (PyO3 0.25: PyDict::new returns Bound<PyDict>)
        // IMPORTANT: Use the same dict for both globals and locals to allow closures
        // to access module-level variables defined in the exec'd code
        let globals = PyDict::new(py);
        globals
            .set_item("qutip", qutip)
            .map_err(|e| BackendError::Python(format!("Failed to set qutip: {}", e)))?;
        globals
            .set_item("np", numpy)
            .map_err(|e| BackendError::Python(format!("Failed to set numpy: {}", e)))?;
        globals
            .set_item("i_envelope", i_array)
            .map_err(|e| BackendError::Python(format!("Failed to set i_envelope: {}", e)))?;
        globals
            .set_item("q_envelope", q_array)
            .map_err(|e| BackendError::Python(format!("Failed to set q_envelope: {}", e)))?;
        globals
            .set_item("num_qubits", self.num_qubits)
            .map_err(|e| BackendError::Python(format!("Failed to set num_qubits: {}", e)))?;
        globals
            .set_item("num_shots", request.num_shots)
            .map_err(|e| BackendError::Python(format!("Failed to set num_shots: {}", e)))?;
        globals
            .set_item("num_time_steps", request.num_time_steps)
            .map_err(|e| BackendError::Python(format!("Failed to set num_time_steps: {}", e)))?;
        globals
            .set_item("duration_ns", request.duration_ns)
            .map_err(|e| BackendError::Python(format!("Failed to set duration_ns: {}", e)))?;

        let target_qubits: Vec<i32> = request.target_qubits.iter().map(|&x| x as i32).collect();
        let target_list = PyList::new(py, &target_qubits).map_err(|e| {
            BackendError::Python(format!("Failed to create target_qubits list: {}", e))
        })?;
        globals
            .set_item("target_qubits", &target_list)
            .map_err(|e| BackendError::Python(format!("Failed to set target_qubits: {}", e)))?;
        globals
            .set_item("return_state_vector", request.return_state_vector)
            .map_err(|e| {
                BackendError::Python(format!("Failed to set return_state_vector: {}", e))
            })?;

        // Python simulation code - fixed for QuTiP 5.x dimension handling
        // Note: Functions defined here can access module-level variables because
        // we use the same dict for both globals and locals
        let code = r#"
import numpy as np
import qutip

# Build operators with proper tensor structure to ensure consistent dimensions
dim = 2 ** num_qubits

# Build identity operators list for tensor products
identity_list = [qutip.qeye(2)] * num_qubits

# Build drift Hamiltonian with proper tensor dimensions
H0 = 0.0 * qutip.tensor(identity_list)

# Build control Hamiltonians for target qubits
Hx_list = []
Hy_list = []

for q in target_qubits:
    ops = [qutip.qeye(2)] * num_qubits
    ops[q] = qutip.sigmax()
    Hx = qutip.tensor(ops)
    Hx_list.append(Hx)
    
    ops = [qutip.qeye(2)] * num_qubits
    ops[q] = qutip.sigmay()
    Hy = qutip.tensor(ops)
    Hy_list.append(Hy)

# Time array (in seconds)
times = np.linspace(0, duration_ns * 1e-9, num_time_steps)
dt = times[1] - times[0] if len(times) > 1 else duration_ns * 1e-9 / max(num_time_steps, 1)

# Build time-dependent Hamiltonian
# Pass dt as parameter to avoid closure scoping issues
def make_coeff(envelope, dt_val):
    def coeff(t, args):
        if len(envelope) == 0:
            return 0.0
        t_idx = int(t / dt_val) if dt_val > 0 else 0
        t_idx = min(t_idx, len(envelope) - 1)
        return envelope[t_idx]
    return coeff

H = [H0]
for i, (Hx, Hy) in enumerate(zip(Hx_list, Hy_list)):
    # Scale factor: convert envelope units to rad/s
    scale = 2 * np.pi * 1e9
    H.append([scale * Hx, make_coeff(i_envelope, dt)])
    H.append([scale * Hy, make_coeff(q_envelope, dt)])

# Initial state: |0...0> with proper tensor dimensions
psi0 = qutip.basis([2] * num_qubits, [0] * num_qubits)

# Run simulation
result = qutip.mesolve(H, psi0, times, [], [])

# Get final state
psi_final = result.states[-1]

# Compute probabilities
probs = np.abs(psi_final.full().flatten()) ** 2

# Ensure probabilities sum to 1 (numerical precision)
probs = probs / np.sum(probs)

# Sample measurements
rng = np.random.default_rng()
samples = rng.choice(dim, size=num_shots, p=probs)

# Count bitstrings
bitstring_counts = {}
for s in samples:
    bitstring = format(s, f'0{num_qubits}b')
    bitstring_counts[bitstring] = bitstring_counts.get(bitstring, 0) + 1

# State vector (if requested)
state_vector = None
if return_state_vector:
    sv = psi_final.full().flatten()
    state_vector = [(float(c.real), float(c.imag)) for c in sv]

# Package results
simulation_result = {
    'bitstring_counts': bitstring_counts,
    'total_shots': num_shots,
    'successful_shots': num_shots,
    'state_vector': state_vector,
    'probabilities': probs.tolist(),
}
"#;

        // Execute Python code
        // Use the same dict for both globals and locals so closures can access variables
        let code_cstr = CString::new(code)
            .map_err(|e| BackendError::Python(format!("Failed to create CString: {}", e)))?;
        py.run(&code_cstr, Some(&globals), Some(&globals))
            .map_err(|e| {
                error!("Python simulation failed: {}", e);
                BackendError::Python(format!("Simulation failed: {}", e))
            })?;

        // Extract results
        let result = globals
            .get_item("simulation_result")
            .map_err(|e| BackendError::Python(format!("Failed to get simulation_result: {}", e)))?
            .ok_or_else(|| BackendError::Python("simulation_result not found".to_string()))?;

        let result_dict = result
            .downcast::<PyDict>()
            .map_err(|e| BackendError::Python(format!("simulation_result is not a dict: {}", e)))?;

        // Extract bitstring counts
        let counts_obj = result_dict
            .get_item("bitstring_counts")
            .map_err(|e| BackendError::Python(format!("Failed to get bitstring_counts: {}", e)))?
            .ok_or_else(|| BackendError::Python("bitstring_counts not found".to_string()))?;

        let counts_dict = counts_obj
            .downcast::<PyDict>()
            .map_err(|e| BackendError::Python(format!("bitstring_counts is not a dict: {}", e)))?;

        let mut bitstring_counts = HashMap::new();
        for (key, value) in counts_dict.iter() {
            let k: String = key.extract::<String>().map_err(|e| {
                BackendError::Python(format!("Failed to extract bitstring key: {}", e))
            })?;
            let v: u32 = value.extract::<u32>().map_err(|e| {
                BackendError::Python(format!("Failed to extract count value: {}", e))
            })?;
            bitstring_counts.insert(k, v);
        }

        // Extract shots
        let total_shots: u32 = result_dict
            .get_item("total_shots")
            .map_err(|e| BackendError::Python(format!("Failed to get total_shots: {}", e)))?
            .ok_or_else(|| BackendError::Python("total_shots not found".to_string()))?
            .extract::<u32>()
            .map_err(|e| BackendError::Python(format!("Failed to extract total_shots: {}", e)))?;

        let successful_shots: u32 = result_dict
            .get_item("successful_shots")
            .map_err(|e| BackendError::Python(format!("Failed to get successful_shots: {}", e)))?
            .ok_or_else(|| BackendError::Python("successful_shots not found".to_string()))?
            .extract::<u32>()
            .map_err(|e| {
                BackendError::Python(format!("Failed to extract successful_shots: {}", e))
            })?;

        // Extract state vector if present
        let state_vector = if request.return_state_vector {
            let sv_obj = result_dict
                .get_item("state_vector")
                .map_err(|e| BackendError::Python(format!("Failed to get state_vector: {}", e)))?;

            match sv_obj {
                Some(sv) if !sv.is_none() => {
                    let sv_list = sv.downcast::<PyList>().map_err(|e| {
                        BackendError::Python(format!("state_vector is not a list: {}", e))
                    })?;

                    let mut vec = Vec::new();
                    for item in sv_list.iter() {
                        let tuple: (f64, f64) = item.extract::<(f64, f64)>().map_err(|e| {
                            BackendError::Python(format!(
                                "Failed to extract state vector element: {}",
                                e
                            ))
                        })?;
                        vec.push(tuple);
                    }
                    Some(vec)
                }
                _ => None,
            }
        } else {
            None
        };

        debug!(
            total_shots = total_shots,
            successful_shots = successful_shots,
            "QuTiP simulation completed"
        );

        Ok(MeasurementResult {
            bitstring_counts,
            total_shots,
            successful_shots,
            quality: ResultQuality::FullSuccess,
            fidelity_estimate: None, // Could compute from state overlap
            state_vector,
        })
    }
}

#[async_trait]
impl QuantumBackend for QutipBackend {
    fn name(&self) -> &str {
        &self.name
    }

    fn backend_type(&self) -> BackendType {
        BackendType::Simulator
    }

    async fn execute_pulse(
        &self,
        request: ExecutePulseRequest,
    ) -> Result<MeasurementResult, BackendError> {
        debug!(
            pulse_id = %request.pulse_id,
            num_shots = request.num_shots,
            "Executing pulse on QuTiP backend"
        );

        // Validate request
        if request.target_qubits.iter().any(|&q| q >= self.num_qubits) {
            return Err(BackendError::InvalidRequest(format!(
                "Target qubit exceeds available qubits (max: {})",
                self.num_qubits - 1
            )));
        }

        if request.num_shots > self.limits.max_shots {
            return Err(BackendError::InvalidRequest(format!(
                "Requested shots {} exceeds limit {}",
                request.num_shots, self.limits.max_shots
            )));
        }

        // Capture backend configuration before spawn_blocking
        let name = self.name.clone();
        let num_qubits = self.num_qubits;
        let limits = self.limits.clone();
        let supports_state_vector = self.supports_state_vector;
        let timeout = self.timeout;

        // Run simulation with timeout to prevent infinite hangs
        let result = tokio::time::timeout(
            timeout,
            tokio::task::spawn_blocking(move || {
                let backend = QutipBackend {
                    name,
                    num_qubits,
                    limits,
                    supports_state_vector,
                    timeout,
                };
                backend.execute_python(&request)
            }),
        )
        .await;

        match result {
            Ok(Ok(inner_result)) => inner_result,
            Ok(Err(join_error)) => Err(BackendError::ExecutionFailed(format!(
                "Task join error: {}",
                join_error
            ))),
            Err(_timeout_error) => {
                error!(
                    timeout_secs = timeout.as_secs(),
                    "Python execution timed out"
                );
                Err(BackendError::ExecutionFailed(format!(
                    "Python execution timed out after {} seconds. \
                     This may indicate an infinite loop or very long simulation.",
                    timeout.as_secs()
                )))
            }
        }
    }

    async fn get_hardware_info(&self) -> Result<HardwareInfo, BackendError> {
        let available_qubits: Vec<u32> = (0..self.num_qubits).collect();

        Ok(HardwareInfo {
            name: self.name.clone(),
            backend_type: BackendType::Simulator,
            tier: "local".to_string(),
            num_qubits: self.num_qubits,
            available_qubits,
            supported_gates: vec![
                "X".to_string(),
                "Y".to_string(),
                "Z".to_string(),
                "H".to_string(),
                "SX".to_string(),
                "RX".to_string(),
                "RY".to_string(),
                "RZ".to_string(),
                "CZ".to_string(),
                "CNOT".to_string(),
                "iSWAP".to_string(),
            ],
            supports_state_vector: self.supports_state_vector,
            supports_noise_model: false,
            software_version: env!("CARGO_PKG_VERSION").to_string(),
            limits: self.limits.clone(),
        })
    }

    async fn health_check(&self) -> Result<HealthStatus, BackendError> {
        if Self::check_qutip_available() {
            Ok(HealthStatus::Healthy)
        } else {
            Ok(HealthStatus::Unavailable)
        }
    }

    fn resource_limits(&self) -> &ResourceLimits {
        &self.limits
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_qutip_availability_check() {
        let available = QutipBackend::check_qutip_available();
        println!("QuTiP available: {}", available);
    }

    #[tokio::test]
    async fn test_hardware_info() {
        let config = QutipConfig::default();
        if let Ok(backend) = QutipBackend::new(&config) {
            let info = backend.get_hardware_info().await.unwrap();
            assert_eq!(info.name, "qutip_simulator");
            assert_eq!(info.backend_type, BackendType::Simulator);
            assert!(info.supports_state_vector);
        }
    }

    #[test]
    fn test_timeout_configuration() {
        let config = QutipConfig::default();
        if let Ok(backend) = QutipBackend::new(&config) {
            let backend = backend.with_timeout(Duration::from_secs(60));
            assert_eq!(backend.timeout.as_secs(), 60);
        }
    }
}
