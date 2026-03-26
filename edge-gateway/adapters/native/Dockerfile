FROM rust:1.85-bookworm AS builder

WORKDIR /build

COPY edge-gateway/Cargo.toml edge-gateway/Cargo.toml
COPY edge-gateway/core edge-gateway/core
COPY edge-gateway/adapters/native edge-gateway/adapters/native

# Stub out workspace members we don't need (they have WASM-only deps)
RUN mkdir -p edge-gateway/adapters/spin/src \
             edge-gateway/adapters/fastly/src \
             edge-gateway/adapters/workers/src \
             edge-gateway/adapters/lambda/src && \
    echo '[package]\nname = "clipclap-gateway-spin"\nversion = "0.1.0"\nedition = "2021"\n[lib]\ncrate-type = ["cdylib"]' > edge-gateway/adapters/spin/Cargo.toml && \
    echo '' > edge-gateway/adapters/spin/src/lib.rs && \
    echo '[package]\nname = "clipclap-gateway-fastly"\nversion = "0.1.0"\nedition = "2021"\n[lib]\ncrate-type = ["cdylib"]' > edge-gateway/adapters/fastly/Cargo.toml && \
    echo '' > edge-gateway/adapters/fastly/src/lib.rs && \
    echo '[package]\nname = "clipclap-gateway-workers"\nversion = "0.1.0"\nedition = "2021"\n[lib]\ncrate-type = ["cdylib"]' > edge-gateway/adapters/workers/Cargo.toml && \
    echo '' > edge-gateway/adapters/workers/src/lib.rs && \
    echo '[package]\nname = "clipclap-gateway-lambda"\nversion = "0.1.0"\nedition = "2021"' > edge-gateway/adapters/lambda/Cargo.toml && \
    echo 'fn main() {}' > edge-gateway/adapters/lambda/src/main.rs

RUN cd edge-gateway && cargo build --release -p clipclap-gateway-native

FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*

COPY --from=builder /build/edge-gateway/target/release/gateway-native /usr/local/bin/gateway-native

ENV PORT=3000
ENV INFERENCE_URL=http://127.0.0.1:8000
ENV GATEWAY_REGION=us-ord

EXPOSE 3000

CMD ["gateway-native"]
