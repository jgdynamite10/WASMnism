.PHONY: build test clean build-spin deploy-spin run-spin build-fastly build-workers build-lambda build-frontend

# ── Build ─────────────────────────────────────────────────────
build:
	cargo build --target wasm32-wasip1 --release

test:
	cargo test

clean:
	cargo clean
	rm -rf adapters/spin/static

# ── Frontend (build + copy to Spin static dir) ───────────────
build-frontend:
	cd ../clipclap/frontend && npm install && npm run build
	mkdir -p adapters/spin/static
	cp -r ../clipclap/frontend/dist/* adapters/spin/static/
	mkdir -p adapters/spin/static/samples/images
	cd adapters/spin/static/samples/images && \
	  curl -sL "https://images.unsplash.com/photo-1514888286974-6c03e2ca1dba?w=640&q=80" -o cat.jpg && \
	  curl -sL "https://images.unsplash.com/photo-1480714378408-67cf0d13bc1b?w=640&q=80" -o street.jpg && \
	  curl -sL "https://images.unsplash.com/photo-1546069901-ba9599a7e63c?w=640&q=80" -o food.jpg && \
	  curl -sL "https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?w=640&q=80" -o mountain.jpg

# ── Spin (Akamai Functions) ──────────────────────────────────
build-spin: build-frontend
	cd adapters/spin && spin build

run-spin:
	cd adapters/spin && \
	SPIN_VARIABLE_INFERENCE_URL=$${INFERENCE_URL:?Set INFERENCE_URL} \
	SPIN_VARIABLE_GATEWAY_REGION=$${GATEWAY_REGION:-us-east-1} \
	spin up

deploy-spin:
	cd adapters/spin && \
	spin cloud deploy \
	  --variable inference_url=$${INFERENCE_URL:?Set INFERENCE_URL} \
	  --variable gateway_region=$${GATEWAY_REGION:-us-ord}

# ── Fastly Compute ───────────────────────────────────────────
build-fastly:
	cargo build --target wasm32-wasip1 --release -p clipclap-gateway-fastly

deploy-fastly:
	cd adapters/fastly && fastly compute deploy --package ../../target/wasm32-wasip1/release/clipclap_gateway_fastly.wasm

# ── Cloudflare Workers ───────────────────────────────────────
build-workers:
	cargo build --target wasm32-unknown-unknown --release -p clipclap-gateway-workers

deploy-workers:
	cd adapters/workers && npx wrangler deploy

# ── AWS Lambda ───────────────────────────────────────────────
build-lambda:
	cd adapters/lambda && cargo lambda build --release --arm64

deploy-lambda:
	cd adapters/lambda && cargo lambda deploy --iam-role $${LAMBDA_ROLE:?Set LAMBDA_ROLE}
