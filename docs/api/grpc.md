# gRPC API

The QubitOS HAL server uses gRPC for high-performance, low-latency communication between the Python client and the Rust HAL server.

!!! info "Primary Interface"
    gRPC is the primary interface for the Python client. The REST API is a convenience wrapper.

## Connection Details

```
Address: localhost:50051
Protocol: gRPC (HTTP/2)
TLS: Optional (recommended for production)
```

Configure via environment:

```bash
export QUBITOS_HAL_HOST=localhost
export QUBITOS_HAL_GRPC_PORT=50051
```

---

## Service Definition

The gRPC service is defined in Protocol Buffer files located in the `qubit-os-proto` repository.

### QuantumBackendService

```protobuf
service QuantumBackendService {
  // Health check
  rpc Health(HealthRequest) returns (HealthResponse);
  
  // List available backends
  rpc ListBackends(ListBackendsRequest) returns (ListBackendsResponse);
  
  // Get backend hardware information
  rpc GetHardwareInfo(GetHardwareInfoRequest) returns (GetHardwareInfoResponse);
  
  // Execute a pulse on a backend
  rpc ExecutePulse(ExecutePulseRequest) returns (ExecutePulseResponse);
}
```

---

## Message Types

### Health Check

```protobuf
message HealthRequest {
  string backend_name = 1;  // Optional: specific backend
}

message HealthResponse {
  HealthStatus status = 1;
  string message = 2;
  repeated BackendStatus backend_statuses = 3;
}

enum HealthStatus {
  HEALTH_STATUS_UNKNOWN = 0;
  HEALTH_STATUS_HEALTHY = 1;
  HEALTH_STATUS_DEGRADED = 2;
  HEALTH_STATUS_UNAVAILABLE = 3;
}
```

### Hardware Info

```protobuf
message GetHardwareInfoRequest {
  string backend_name = 1;
}

message GetHardwareInfoResponse {
  HardwareInfo info = 1;
}

message HardwareInfo {
  string name = 1;
  BackendType backend_type = 2;
  string tier = 3;
  int32 num_qubits = 4;
  repeated int32 available_qubits = 5;
  repeated string supported_gates = 6;
  bool supports_state_vector = 7;
  bool supports_noise_model = 8;
  string software_version = 9;
}
```

### Pulse Execution

```protobuf
message ExecutePulseRequest {
  string backend_name = 1;
  PulseShape pulse = 2;
  int32 num_shots = 3;
  string measurement_basis = 4;
  repeated int32 measurement_qubits = 5;
  bool return_state_vector = 6;
  bool include_noise = 7;
}

message PulseShape {
  string pulse_id = 1;
  string algorithm = 2;
  GateType gate_type = 3;
  repeated int32 target_qubit_indices = 4;
  int32 duration_ns = 5;
  int32 num_time_steps = 6;
  double time_step_ns = 7;
  repeated double i_envelope = 8;
  repeated double q_envelope = 9;
}

message ExecutePulseResponse {
  bool success = 1;
  ExecutionResult result = 2;
  ExecutionError error = 3;
}

message ExecutionResult {
  string pulse_id = 1;
  int32 total_shots = 2;
  int32 successful_shots = 3;
  map<string, int32> bitstring_counts = 4;
  double fidelity_estimate = 5;
  StateVector state_vector = 6;
}
```

---

## Using from Python

The Python client abstracts gRPC details:

```python
from qubitos.client import HALClient

async with HALClient("localhost:50051") as client:
    # These methods use gRPC internally
    health = await client.health_check()
    result = await client.execute_pulse(...)
```

### Direct gRPC Usage

For advanced use cases, access gRPC directly:

```python
import grpc
from qubitos.proto import (
    HealthRequest,
    QuantumBackendServiceStub,
)

# Create channel
channel = grpc.aio.insecure_channel("localhost:50051")
stub = QuantumBackendServiceStub(channel)

# Make RPC call
request = HealthRequest(backend_name="")
response = await stub.Health(request, timeout=30.0)
print(f"Status: {response.status}")

await channel.close()
```

---

## Using from Other Languages

### Rust

```rust
use tonic::transport::Channel;
use quantum_backend::quantum_backend_service_client::QuantumBackendServiceClient;
use quantum_backend::HealthRequest;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let channel = Channel::from_static("http://localhost:50051")
        .connect()
        .await?;
    
    let mut client = QuantumBackendServiceClient::new(channel);
    
    let request = tonic::Request::new(HealthRequest {
        backend_name: String::new(),
    });
    
    let response = client.health(request).await?;
    println!("Status: {:?}", response.get_ref().status);
    
    Ok(())
}
```

### Go

```go
package main

import (
    "context"
    "log"
    
    pb "github.com/qubit-os/qubit-os-proto/gen/go/quantum/backend/v1"
    "google.golang.org/grpc"
    "google.golang.org/grpc/credentials/insecure"
)

func main() {
    conn, err := grpc.Dial(
        "localhost:50051",
        grpc.WithTransportCredentials(insecure.NewCredentials()),
    )
    if err != nil {
        log.Fatalf("Failed to connect: %v", err)
    }
    defer conn.Close()
    
    client := pb.NewQuantumBackendServiceClient(conn)
    
    resp, err := client.Health(context.Background(), &pb.HealthRequest{})
    if err != nil {
        log.Fatalf("Health check failed: %v", err)
    }
    
    log.Printf("Status: %v", resp.Status)
}
```

### C++

```cpp
#include <grpcpp/grpcpp.h>
#include "quantum/backend/v1/service.grpc.pb.h"

int main() {
    auto channel = grpc::CreateChannel(
        "localhost:50051",
        grpc::InsecureChannelCredentials()
    );
    auto stub = quantum::backend::v1::QuantumBackendService::NewStub(channel);
    
    grpc::ClientContext context;
    quantum::backend::v1::HealthRequest request;
    quantum::backend::v1::HealthResponse response;
    
    auto status = stub->Health(&context, request, &response);
    if (status.ok()) {
        std::cout << "Status: " << response.status() << std::endl;
    }
    
    return 0;
}
```

---

## TLS Configuration

For production, use TLS:

```python
import grpc

# Load credentials
with open("ca.pem", "rb") as f:
    ca_cert = f.read()

credentials = grpc.ssl_channel_credentials(root_certificates=ca_cert)

# Create secure channel
channel = grpc.aio.secure_channel("hal.example.com:50051", credentials)
```

Server-side configuration:

```bash
export HAL_TLS_CERT=/path/to/server.pem
export HAL_TLS_KEY=/path/to/server.key
```

---

## Error Handling

gRPC errors include status codes and details:

```python
import grpc
from qubitos.client import HALClientError

try:
    result = await client.execute_pulse(...)
except HALClientError as e:
    print(f"Error: {e}")
    print(f"gRPC code: {e.code}")  # e.g., "UNAVAILABLE"
```

### Common Status Codes

| Code | Meaning |
|------|---------|
| `OK` | Success |
| `CANCELLED` | Operation cancelled |
| `UNKNOWN` | Unknown error |
| `INVALID_ARGUMENT` | Invalid request |
| `DEADLINE_EXCEEDED` | Timeout |
| `NOT_FOUND` | Resource not found |
| `ALREADY_EXISTS` | Resource exists |
| `PERMISSION_DENIED` | Not authorized |
| `RESOURCE_EXHAUSTED` | Rate limited |
| `UNAVAILABLE` | Server unavailable |
| `INTERNAL` | Server error |

---

## Protocol Buffers

Proto files are in the `qubit-os-proto` repository:

```
qubit-os-proto/
├── quantum/
│   ├── common/v1/
│   │   └── common.proto
│   ├── pulse/v1/
│   │   ├── pulse.proto
│   │   ├── grape.proto
│   │   └── hamiltonian.proto
│   └── backend/v1/
│       ├── service.proto
│       ├── hardware.proto
│       └── execution.proto
```

### Generating Stubs

Python stubs are pre-generated. To regenerate:

```bash
cd qubit-os-proto
pip install grpcio-tools
python -m grpc_tools.protoc \
  -I. \
  --python_out=../qubit-os-core/src/qubitos/proto \
  --grpc_python_out=../qubit-os-core/src/qubitos/proto \
  quantum/**/*.proto
```

---

## Performance

gRPC provides significant performance benefits:

| Metric | REST | gRPC |
|--------|------|------|
| Serialization | JSON | Protobuf (binary) |
| Connection | HTTP/1.1 | HTTP/2 (multiplexed) |
| Latency | ~5ms | ~1ms |
| Throughput | 100 req/s | 1000+ req/s |

### Connection Pooling

The Python client maintains a persistent connection:

```python
# Good: Reuse client
async with HALClient("localhost:50051") as client:
    for i in range(100):
        await client.execute_pulse(...)  # Reuses connection

# Bad: New connection each time
for i in range(100):
    async with HALClient("localhost:50051") as client:
        await client.execute_pulse(...)  # New connection overhead
```

---

## Streaming (Future)

gRPC streaming will enable:

- Real-time pulse optimization feedback
- Continuous measurement streams
- Batch pulse execution

```protobuf
// Future API
service QuantumBackendService {
  // Streaming pulse execution
  rpc ExecutePulseStream(stream PulseShape) returns (stream ExecutionResult);
  
  // Optimization with progress
  rpc OptimizePulse(OptimizeRequest) returns (stream OptimizeProgress);
}
```
