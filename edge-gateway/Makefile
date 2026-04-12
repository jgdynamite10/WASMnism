.PHONY: build test clean build-spin deploy-akamai run-spin build-fastly deploy-fastly build-workers build-frontend

# ── Build ─────────────────────────────────────────────────────
build:
	cargo build --target wasm32-wasip1 --release

test:
	cargo test

clean:
	cargo clean
	rm -rf adapters/spin/static adapters/fastly/static adapters/workers/static

# ── Frontend (build + copy to adapter static dirs) ───────────
build-frontend:
	cd ../frontend && npm install && npm run build
	mkdir -p adapters/spin/static
	cp -r ../frontend/dist/* adapters/spin/static/
	mkdir -p adapters/fastly/static
	cp -r ../frontend/dist/* adapters/fastly/static/
	mkdir -p adapters/lambda/static
	cp -r ../frontend/dist/* adapters/lambda/static/
	mkdir -p adapters/workers/static
	cp -r ../frontend/dist/* adapters/workers/static/

# ── Spin (Akamai Functions) ──────────────────────────────────
build-spin: build-frontend
	cd adapters/spin && spin build

run-spin:
	cd adapters/spin && \
	SPIN_VARIABLE_GATEWAY_REGION=$${GATEWAY_REGION:-local} \
	spin up

deploy-akamai:
	cd adapters/spin && \
	spin aka deploy --no-confirm \
	  --variable "gateway_platform=Akamai Functions" \
	  --variable "gateway_region=$${GATEWAY_REGION:-global (edge)}"

# ── Fastly Compute ───────────────────────────────────────────
build-fastly: build-frontend
	cd adapters/fastly && fastly compute build

deploy-fastly: build-frontend
	cd adapters/fastly && fastly compute publish --non-interactive --status-check-off

# ── Cloudflare Workers ───────────────────────────────────────
build-workers:
	cargo build --target wasm32-unknown-unknown --release -p clipclap-gateway-workers

deploy-workers: build-frontend
	cd adapters/workers && npx wrangler deploy

