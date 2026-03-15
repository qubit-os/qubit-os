// Copyright 2026 QubitOS Contributors
// SPDX-License-Identifier: Apache-2.0

//! Build script for qubit-os-hardware.
//! Compiles Protocol Buffer definitions into Rust code.
//!
//! Set SKIP_PROTO_BUILD=1 to skip proto compilation (useful in CI without protoc).

use std::env;
use std::path::PathBuf;
use std::process::Command;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Check if we should skip proto build
    if env::var("SKIP_PROTO_BUILD").is_ok() {
        println!("cargo:warning=Skipping proto build (SKIP_PROTO_BUILD is set)");
        return Ok(());
    }

    // Check if protoc is available
    let protoc_available = Command::new("protoc")
        .arg("--version")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false);

    if !protoc_available {
        println!("cargo:warning=protoc not found, skipping proto compilation");
        println!(
            "cargo:warning=To compile protos, install protoc: apt-get install protobuf-compiler"
        );
        println!("cargo:warning=Using stub proto types instead");
        return Ok(());
    }

    // Get the proto files from qubit-os-proto
    let proto_root = PathBuf::from(env::var("CARGO_MANIFEST_DIR")?)
        .parent()
        .unwrap()
        .join("qubit-os-proto");

    // Check if proto directory exists
    if !proto_root.exists() {
        println!("cargo:warning=Proto directory not found: {:?}", proto_root);
        println!("cargo:warning=Using stub proto types instead");
        return Ok(());
    }

    let proto_files = [
        "quantum/common/v1/common.proto",
        "quantum/pulse/v1/hamiltonian.proto",
        "quantum/pulse/v1/pulse.proto",
        "quantum/pulse/v1/temporal.proto",
        "quantum/pulse/v1/grape.proto",
        "quantum/error/v1/error_budget.proto",
        "quantum/provenance/v1/provenance.proto",
        "quantum/backend/v1/service.proto",
        "quantum/backend/v1/execution.proto",
        "quantum/backend/v1/hardware.proto",
    ];

    let proto_paths: Vec<PathBuf> = proto_files.iter().map(|f| proto_root.join(f)).collect();

    // Check if all proto files exist
    let all_exist = proto_paths.iter().all(|p| p.exists());
    if !all_exist {
        for path in &proto_paths {
            if !path.exists() {
                println!("cargo:warning=Proto file not found: {:?}", path);
            }
        }
        println!("cargo:warning=Some proto files missing, using stub types");
        return Ok(());
    }

    // Configure tonic-build
    // Note: compile_protos is the current non-deprecated method name
    tonic_build::configure()
        .build_server(true)
        .build_client(true)
        .out_dir("src/proto/generated")
        .compile_protos(
            &proto_paths
                .iter()
                .map(|p| p.to_str().unwrap())
                .collect::<Vec<_>>(),
            &[proto_root.to_str().unwrap()],
        )?;

    // Tell cargo to rerun if proto files change
    for path in &proto_paths {
        println!("cargo:rerun-if-changed={}", path.display());
    }

    Ok(())
}
