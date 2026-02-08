// build.rs - Compile protos at build time
// No committed generated code - this runs on `cargo build`

fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Tell Cargo to rerun if any proto file changes
    println!("cargo:rerun-if-changed=quantum/");

    let protos = &[
        "quantum/common/v1/common.proto",
        "quantum/pulse/v1/pulse.proto",
        "quantum/pulse/v1/hamiltonian.proto",
        "quantum/pulse/v1/grape.proto",
        "quantum/backend/v1/service.proto",
        "quantum/backend/v1/execution.proto",
        "quantum/backend/v1/hardware.proto",
    ];

    let includes = &["."];

    tonic_build::configure()
        .build_server(true)
        .build_client(true)
        .compile_protos(protos, includes)?;

    Ok(())
}
