# QubitOS HAL Server Dockerfile
# Multi-stage build for minimal image size

# Build stage
FROM rust:1.85-bookworm AS builder

WORKDIR /app

# Install Python for PyO3
RUN apt-get update && apt-get install -y \
    python3-dev \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Copy manifests first for layer caching
COPY Cargo.toml Cargo.lock ./
COPY build.rs ./

# Create dummy src to build dependencies
RUN mkdir src && \
    echo "fn main() {}" > src/main.rs && \
    echo "pub fn lib() {}" > src/lib.rs

# Build dependencies only
RUN cargo build --release && rm -rf src

# Copy actual source
COPY src/ src/

# Build the application
RUN touch src/main.rs src/lib.rs && cargo build --release

# Runtime stage
FROM debian:bookworm-slim

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies for QuTiP backend
RUN pip3 install --break-system-packages "qutip>=5.0.0,<6.0.0" "numpy>=1.26.0,<2.0.0" "scipy>=1.12.0,<2.0.0"

# Copy binary from builder
COPY --from=builder /app/target/release/qubit-os-hal /usr/local/bin/

# Create non-root user
RUN useradd -r -s /bin/false qubitos
USER qubitos

# Expose ports
EXPOSE 50051 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD ["/usr/local/bin/qubit-os-hal", "health"] || exit 1

ENTRYPOINT ["/usr/local/bin/qubit-os-hal"]
CMD ["serve"]
