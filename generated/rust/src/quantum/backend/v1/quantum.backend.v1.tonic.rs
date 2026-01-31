// @generated
/// Generated client implementations.
pub mod quantum_backend_service_client {
    #![allow(
        unused_variables,
        dead_code,
        missing_docs,
        clippy::wildcard_imports,
        clippy::let_unit_value,
    )]
    use tonic::codegen::*;
    use tonic::codegen::http::Uri;
    /** QuantumBackendService provides access to quantum hardware and simulators.

 This is the primary interface for executing pulses and querying backend
 capabilities. All pulse execution flows through this service.

 Supported backends:
 - qutip_simulator: Local QuTiP-based simulator (always available)
 - iqm_garnet: IQM Garnet quantum processor (requires credentials)
*/
    #[derive(Debug, Clone)]
    pub struct QuantumBackendServiceClient<T> {
        inner: tonic::client::Grpc<T>,
    }
    impl QuantumBackendServiceClient<tonic::transport::Channel> {
        /// Attempt to create a new client by connecting to a given endpoint.
        pub async fn connect<D>(dst: D) -> Result<Self, tonic::transport::Error>
        where
            D: TryInto<tonic::transport::Endpoint>,
            D::Error: Into<StdError>,
        {
            let conn = tonic::transport::Endpoint::new(dst)?.connect().await?;
            Ok(Self::new(conn))
        }
    }
    impl<T> QuantumBackendServiceClient<T>
    where
        T: tonic::client::GrpcService<tonic::body::Body>,
        T::Error: Into<StdError>,
        T::ResponseBody: Body<Data = Bytes> + std::marker::Send + 'static,
        <T::ResponseBody as Body>::Error: Into<StdError> + std::marker::Send,
    {
        pub fn new(inner: T) -> Self {
            let inner = tonic::client::Grpc::new(inner);
            Self { inner }
        }
        pub fn with_origin(inner: T, origin: Uri) -> Self {
            let inner = tonic::client::Grpc::with_origin(inner, origin);
            Self { inner }
        }
        pub fn with_interceptor<F>(
            inner: T,
            interceptor: F,
        ) -> QuantumBackendServiceClient<InterceptedService<T, F>>
        where
            F: tonic::service::Interceptor,
            T::ResponseBody: Default,
            T: tonic::codegen::Service<
                http::Request<tonic::body::Body>,
                Response = http::Response<
                    <T as tonic::client::GrpcService<tonic::body::Body>>::ResponseBody,
                >,
            >,
            <T as tonic::codegen::Service<
                http::Request<tonic::body::Body>,
            >>::Error: Into<StdError> + std::marker::Send + std::marker::Sync,
        {
            QuantumBackendServiceClient::new(InterceptedService::new(inner, interceptor))
        }
        /// Compress requests with the given encoding.
        ///
        /// This requires the server to support it otherwise it might respond with an
        /// error.
        #[must_use]
        pub fn send_compressed(mut self, encoding: CompressionEncoding) -> Self {
            self.inner = self.inner.send_compressed(encoding);
            self
        }
        /// Enable decompressing responses.
        #[must_use]
        pub fn accept_compressed(mut self, encoding: CompressionEncoding) -> Self {
            self.inner = self.inner.accept_compressed(encoding);
            self
        }
        /// Limits the maximum size of a decoded message.
        ///
        /// Default: `4MB`
        #[must_use]
        pub fn max_decoding_message_size(mut self, limit: usize) -> Self {
            self.inner = self.inner.max_decoding_message_size(limit);
            self
        }
        /// Limits the maximum size of an encoded message.
        ///
        /// Default: `usize::MAX`
        #[must_use]
        pub fn max_encoding_message_size(mut self, limit: usize) -> Self {
            self.inner = self.inner.max_encoding_message_size(limit);
            self
        }
        /** Execute a single pulse on the specified backend.

 The pulse is validated before execution. If validation fails,
 returns INVALID_ARGUMENT error.

 For simulators: returns measurement samples from the final state.
 For hardware: submits to queue and returns when complete.
*/
        pub async fn execute_pulse(
            &mut self,
            request: impl tonic::IntoRequest<super::ExecutePulseRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ExecutePulseResponse>,
            tonic::Status,
        > {
            self.inner
                .ready()
                .await
                .map_err(|e| {
                    tonic::Status::unknown(
                        format!("Service was not ready: {}", e.into()),
                    )
                })?;
            let codec = tonic_prost::ProstCodec::default();
            let path = http::uri::PathAndQuery::from_static(
                "/quantum.backend.v1.QuantumBackendService/ExecutePulse",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "quantum.backend.v1.QuantumBackendService",
                        "ExecutePulse",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** Execute multiple pulses in a batch.

 More efficient than individual calls when running many pulses.
 Can optionally stop on first error or continue despite failures.
*/
        pub async fn execute_pulse_batch(
            &mut self,
            request: impl tonic::IntoRequest<super::ExecutePulseBatchRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ExecutePulseBatchResponse>,
            tonic::Status,
        > {
            self.inner
                .ready()
                .await
                .map_err(|e| {
                    tonic::Status::unknown(
                        format!("Service was not ready: {}", e.into()),
                    )
                })?;
            let codec = tonic_prost::ProstCodec::default();
            let path = http::uri::PathAndQuery::from_static(
                "/quantum.backend.v1.QuantumBackendService/ExecutePulseBatch",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "quantum.backend.v1.QuantumBackendService",
                        "ExecutePulseBatch",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** Get detailed information about a backend.

 Returns capabilities, resource limits, connectivity, and current status.
*/
        pub async fn get_hardware_info(
            &mut self,
            request: impl tonic::IntoRequest<super::GetHardwareInfoRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetHardwareInfoResponse>,
            tonic::Status,
        > {
            self.inner
                .ready()
                .await
                .map_err(|e| {
                    tonic::Status::unknown(
                        format!("Service was not ready: {}", e.into()),
                    )
                })?;
            let codec = tonic_prost::ProstCodec::default();
            let path = http::uri::PathAndQuery::from_static(
                "/quantum.backend.v1.QuantumBackendService/GetHardwareInfo",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "quantum.backend.v1.QuantumBackendService",
                        "GetHardwareInfo",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** Check health of a specific backend or all backends.

 Use for monitoring and to check availability before submitting jobs.
*/
        pub async fn health(
            &mut self,
            request: impl tonic::IntoRequest<super::HealthRequest>,
        ) -> std::result::Result<tonic::Response<super::HealthResponse>, tonic::Status> {
            self.inner
                .ready()
                .await
                .map_err(|e| {
                    tonic::Status::unknown(
                        format!("Service was not ready: {}", e.into()),
                    )
                })?;
            let codec = tonic_prost::ProstCodec::default();
            let path = http::uri::PathAndQuery::from_static(
                "/quantum.backend.v1.QuantumBackendService/Health",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new("quantum.backend.v1.QuantumBackendService", "Health"),
                );
            self.inner.unary(req, path, codec).await
        }
        /** List all available backends.
*/
        pub async fn list_backends(
            &mut self,
            request: impl tonic::IntoRequest<super::ListBackendsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListBackendsResponse>,
            tonic::Status,
        > {
            self.inner
                .ready()
                .await
                .map_err(|e| {
                    tonic::Status::unknown(
                        format!("Service was not ready: {}", e.into()),
                    )
                })?;
            let codec = tonic_prost::ProstCodec::default();
            let path = http::uri::PathAndQuery::from_static(
                "/quantum.backend.v1.QuantumBackendService/ListBackends",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "quantum.backend.v1.QuantumBackendService",
                        "ListBackends",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
    }
}
/// Generated server implementations.
pub mod quantum_backend_service_server {
    #![allow(
        unused_variables,
        dead_code,
        missing_docs,
        clippy::wildcard_imports,
        clippy::let_unit_value,
    )]
    use tonic::codegen::*;
    /// Generated trait containing gRPC methods that should be implemented for use with QuantumBackendServiceServer.
    #[async_trait]
    pub trait QuantumBackendService: std::marker::Send + std::marker::Sync + 'static {
        /** Execute a single pulse on the specified backend.

 The pulse is validated before execution. If validation fails,
 returns INVALID_ARGUMENT error.

 For simulators: returns measurement samples from the final state.
 For hardware: submits to queue and returns when complete.
*/
        async fn execute_pulse(
            &self,
            request: tonic::Request<super::ExecutePulseRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ExecutePulseResponse>,
            tonic::Status,
        >;
        /** Execute multiple pulses in a batch.

 More efficient than individual calls when running many pulses.
 Can optionally stop on first error or continue despite failures.
*/
        async fn execute_pulse_batch(
            &self,
            request: tonic::Request<super::ExecutePulseBatchRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ExecutePulseBatchResponse>,
            tonic::Status,
        >;
        /** Get detailed information about a backend.

 Returns capabilities, resource limits, connectivity, and current status.
*/
        async fn get_hardware_info(
            &self,
            request: tonic::Request<super::GetHardwareInfoRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetHardwareInfoResponse>,
            tonic::Status,
        >;
        /** Check health of a specific backend or all backends.

 Use for monitoring and to check availability before submitting jobs.
*/
        async fn health(
            &self,
            request: tonic::Request<super::HealthRequest>,
        ) -> std::result::Result<tonic::Response<super::HealthResponse>, tonic::Status>;
        /** List all available backends.
*/
        async fn list_backends(
            &self,
            request: tonic::Request<super::ListBackendsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListBackendsResponse>,
            tonic::Status,
        >;
    }
    /** QuantumBackendService provides access to quantum hardware and simulators.

 This is the primary interface for executing pulses and querying backend
 capabilities. All pulse execution flows through this service.

 Supported backends:
 - qutip_simulator: Local QuTiP-based simulator (always available)
 - iqm_garnet: IQM Garnet quantum processor (requires credentials)
*/
    #[derive(Debug)]
    pub struct QuantumBackendServiceServer<T> {
        inner: Arc<T>,
        accept_compression_encodings: EnabledCompressionEncodings,
        send_compression_encodings: EnabledCompressionEncodings,
        max_decoding_message_size: Option<usize>,
        max_encoding_message_size: Option<usize>,
    }
    impl<T> QuantumBackendServiceServer<T> {
        pub fn new(inner: T) -> Self {
            Self::from_arc(Arc::new(inner))
        }
        pub fn from_arc(inner: Arc<T>) -> Self {
            Self {
                inner,
                accept_compression_encodings: Default::default(),
                send_compression_encodings: Default::default(),
                max_decoding_message_size: None,
                max_encoding_message_size: None,
            }
        }
        pub fn with_interceptor<F>(
            inner: T,
            interceptor: F,
        ) -> InterceptedService<Self, F>
        where
            F: tonic::service::Interceptor,
        {
            InterceptedService::new(Self::new(inner), interceptor)
        }
        /// Enable decompressing requests with the given encoding.
        #[must_use]
        pub fn accept_compressed(mut self, encoding: CompressionEncoding) -> Self {
            self.accept_compression_encodings.enable(encoding);
            self
        }
        /// Compress responses with the given encoding, if the client supports it.
        #[must_use]
        pub fn send_compressed(mut self, encoding: CompressionEncoding) -> Self {
            self.send_compression_encodings.enable(encoding);
            self
        }
        /// Limits the maximum size of a decoded message.
        ///
        /// Default: `4MB`
        #[must_use]
        pub fn max_decoding_message_size(mut self, limit: usize) -> Self {
            self.max_decoding_message_size = Some(limit);
            self
        }
        /// Limits the maximum size of an encoded message.
        ///
        /// Default: `usize::MAX`
        #[must_use]
        pub fn max_encoding_message_size(mut self, limit: usize) -> Self {
            self.max_encoding_message_size = Some(limit);
            self
        }
    }
    impl<T, B> tonic::codegen::Service<http::Request<B>>
    for QuantumBackendServiceServer<T>
    where
        T: QuantumBackendService,
        B: Body + std::marker::Send + 'static,
        B::Error: Into<StdError> + std::marker::Send + 'static,
    {
        type Response = http::Response<tonic::body::Body>;
        type Error = std::convert::Infallible;
        type Future = BoxFuture<Self::Response, Self::Error>;
        fn poll_ready(
            &mut self,
            _cx: &mut Context<'_>,
        ) -> Poll<std::result::Result<(), Self::Error>> {
            Poll::Ready(Ok(()))
        }
        fn call(&mut self, req: http::Request<B>) -> Self::Future {
            match req.uri().path() {
                "/quantum.backend.v1.QuantumBackendService/ExecutePulse" => {
                    #[allow(non_camel_case_types)]
                    struct ExecutePulseSvc<T: QuantumBackendService>(pub Arc<T>);
                    impl<
                        T: QuantumBackendService,
                    > tonic::server::UnaryService<super::ExecutePulseRequest>
                    for ExecutePulseSvc<T> {
                        type Response = super::ExecutePulseResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::ExecutePulseRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as QuantumBackendService>::execute_pulse(&inner, request)
                                    .await
                            };
                            Box::pin(fut)
                        }
                    }
                    let accept_compression_encodings = self.accept_compression_encodings;
                    let send_compression_encodings = self.send_compression_encodings;
                    let max_decoding_message_size = self.max_decoding_message_size;
                    let max_encoding_message_size = self.max_encoding_message_size;
                    let inner = self.inner.clone();
                    let fut = async move {
                        let method = ExecutePulseSvc(inner);
                        let codec = tonic_prost::ProstCodec::default();
                        let mut grpc = tonic::server::Grpc::new(codec)
                            .apply_compression_config(
                                accept_compression_encodings,
                                send_compression_encodings,
                            )
                            .apply_max_message_size_config(
                                max_decoding_message_size,
                                max_encoding_message_size,
                            );
                        let res = grpc.unary(method, req).await;
                        Ok(res)
                    };
                    Box::pin(fut)
                }
                "/quantum.backend.v1.QuantumBackendService/ExecutePulseBatch" => {
                    #[allow(non_camel_case_types)]
                    struct ExecutePulseBatchSvc<T: QuantumBackendService>(pub Arc<T>);
                    impl<
                        T: QuantumBackendService,
                    > tonic::server::UnaryService<super::ExecutePulseBatchRequest>
                    for ExecutePulseBatchSvc<T> {
                        type Response = super::ExecutePulseBatchResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::ExecutePulseBatchRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as QuantumBackendService>::execute_pulse_batch(
                                        &inner,
                                        request,
                                    )
                                    .await
                            };
                            Box::pin(fut)
                        }
                    }
                    let accept_compression_encodings = self.accept_compression_encodings;
                    let send_compression_encodings = self.send_compression_encodings;
                    let max_decoding_message_size = self.max_decoding_message_size;
                    let max_encoding_message_size = self.max_encoding_message_size;
                    let inner = self.inner.clone();
                    let fut = async move {
                        let method = ExecutePulseBatchSvc(inner);
                        let codec = tonic_prost::ProstCodec::default();
                        let mut grpc = tonic::server::Grpc::new(codec)
                            .apply_compression_config(
                                accept_compression_encodings,
                                send_compression_encodings,
                            )
                            .apply_max_message_size_config(
                                max_decoding_message_size,
                                max_encoding_message_size,
                            );
                        let res = grpc.unary(method, req).await;
                        Ok(res)
                    };
                    Box::pin(fut)
                }
                "/quantum.backend.v1.QuantumBackendService/GetHardwareInfo" => {
                    #[allow(non_camel_case_types)]
                    struct GetHardwareInfoSvc<T: QuantumBackendService>(pub Arc<T>);
                    impl<
                        T: QuantumBackendService,
                    > tonic::server::UnaryService<super::GetHardwareInfoRequest>
                    for GetHardwareInfoSvc<T> {
                        type Response = super::GetHardwareInfoResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::GetHardwareInfoRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as QuantumBackendService>::get_hardware_info(
                                        &inner,
                                        request,
                                    )
                                    .await
                            };
                            Box::pin(fut)
                        }
                    }
                    let accept_compression_encodings = self.accept_compression_encodings;
                    let send_compression_encodings = self.send_compression_encodings;
                    let max_decoding_message_size = self.max_decoding_message_size;
                    let max_encoding_message_size = self.max_encoding_message_size;
                    let inner = self.inner.clone();
                    let fut = async move {
                        let method = GetHardwareInfoSvc(inner);
                        let codec = tonic_prost::ProstCodec::default();
                        let mut grpc = tonic::server::Grpc::new(codec)
                            .apply_compression_config(
                                accept_compression_encodings,
                                send_compression_encodings,
                            )
                            .apply_max_message_size_config(
                                max_decoding_message_size,
                                max_encoding_message_size,
                            );
                        let res = grpc.unary(method, req).await;
                        Ok(res)
                    };
                    Box::pin(fut)
                }
                "/quantum.backend.v1.QuantumBackendService/Health" => {
                    #[allow(non_camel_case_types)]
                    struct HealthSvc<T: QuantumBackendService>(pub Arc<T>);
                    impl<
                        T: QuantumBackendService,
                    > tonic::server::UnaryService<super::HealthRequest>
                    for HealthSvc<T> {
                        type Response = super::HealthResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::HealthRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as QuantumBackendService>::health(&inner, request).await
                            };
                            Box::pin(fut)
                        }
                    }
                    let accept_compression_encodings = self.accept_compression_encodings;
                    let send_compression_encodings = self.send_compression_encodings;
                    let max_decoding_message_size = self.max_decoding_message_size;
                    let max_encoding_message_size = self.max_encoding_message_size;
                    let inner = self.inner.clone();
                    let fut = async move {
                        let method = HealthSvc(inner);
                        let codec = tonic_prost::ProstCodec::default();
                        let mut grpc = tonic::server::Grpc::new(codec)
                            .apply_compression_config(
                                accept_compression_encodings,
                                send_compression_encodings,
                            )
                            .apply_max_message_size_config(
                                max_decoding_message_size,
                                max_encoding_message_size,
                            );
                        let res = grpc.unary(method, req).await;
                        Ok(res)
                    };
                    Box::pin(fut)
                }
                "/quantum.backend.v1.QuantumBackendService/ListBackends" => {
                    #[allow(non_camel_case_types)]
                    struct ListBackendsSvc<T: QuantumBackendService>(pub Arc<T>);
                    impl<
                        T: QuantumBackendService,
                    > tonic::server::UnaryService<super::ListBackendsRequest>
                    for ListBackendsSvc<T> {
                        type Response = super::ListBackendsResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::ListBackendsRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as QuantumBackendService>::list_backends(&inner, request)
                                    .await
                            };
                            Box::pin(fut)
                        }
                    }
                    let accept_compression_encodings = self.accept_compression_encodings;
                    let send_compression_encodings = self.send_compression_encodings;
                    let max_decoding_message_size = self.max_decoding_message_size;
                    let max_encoding_message_size = self.max_encoding_message_size;
                    let inner = self.inner.clone();
                    let fut = async move {
                        let method = ListBackendsSvc(inner);
                        let codec = tonic_prost::ProstCodec::default();
                        let mut grpc = tonic::server::Grpc::new(codec)
                            .apply_compression_config(
                                accept_compression_encodings,
                                send_compression_encodings,
                            )
                            .apply_max_message_size_config(
                                max_decoding_message_size,
                                max_encoding_message_size,
                            );
                        let res = grpc.unary(method, req).await;
                        Ok(res)
                    };
                    Box::pin(fut)
                }
                _ => {
                    Box::pin(async move {
                        let mut response = http::Response::new(
                            tonic::body::Body::default(),
                        );
                        let headers = response.headers_mut();
                        headers
                            .insert(
                                tonic::Status::GRPC_STATUS,
                                (tonic::Code::Unimplemented as i32).into(),
                            );
                        headers
                            .insert(
                                http::header::CONTENT_TYPE,
                                tonic::metadata::GRPC_CONTENT_TYPE,
                            );
                        Ok(response)
                    })
                }
            }
        }
    }
    impl<T> Clone for QuantumBackendServiceServer<T> {
        fn clone(&self) -> Self {
            let inner = self.inner.clone();
            Self {
                inner,
                accept_compression_encodings: self.accept_compression_encodings,
                send_compression_encodings: self.send_compression_encodings,
                max_decoding_message_size: self.max_decoding_message_size,
                max_encoding_message_size: self.max_encoding_message_size,
            }
        }
    }
    /// Generated gRPC service name
    pub const SERVICE_NAME: &str = "quantum.backend.v1.QuantumBackendService";
    impl<T> tonic::server::NamedService for QuantumBackendServiceServer<T> {
        const NAME: &'static str = SERVICE_NAME;
    }
}
