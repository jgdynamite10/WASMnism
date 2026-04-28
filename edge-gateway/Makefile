.PHONY: build test clean build-spin deploy-spin deploy-akamai run-spin build-fastly deploy-fastly build-workers build-lambda build-frontend

# ── Build ─────────────────────────────────────────────────────
build:
	cargo build --target wasm32-wasip1 --release

test:
	cargo test

clean:
	cargo clean
	rm -rf adapters/spin/static adapters/fastly/static adapters/lambda/static adapters/lambda/models adapters/workers/static

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

deploy-spin:
	cd adapters/spin && \
	spin cloud deploy \
	  --variable "gateway_platform=Fermyon Cloud" \
	  --variable "gateway_region=$${GATEWAY_REGION:-global (edge)}"

# Set INFERENCE_URL to your Lambda Function URL (HTTPS, no trailing path) so Spin can reach Tier 2 classify.
deploy-akamai:
	cd adapters/spin && \
	spin aka deploy --no-confirm \
	  --variable "gateway_platform=Akamai Functions" \
	  --variable "gateway_region=$${GATEWAY_REGION:-global (edge)}" \
	  --variable "inference_url=$${INFERENCE_URL:-}"

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

# ── AWS Lambda ───────────────────────────────────────────────
build-lambda: build-frontend
	cd adapters/lambda && cargo lambda build --release --arm64

stage-lambda-models:
	mkdir -p adapters/lambda/models/toxicity
	cp models/toxicity/model.nnef.tar adapters/lambda/models/toxicity/
	cp models/toxicity/vocab.txt adapters/lambda/models/toxicity/

deploy-lambda: build-frontend stage-lambda-models
	cd adapters/lambda && cargo lambda deploy $${LAMBDA_FUNCTION_NAME:-wasmnism-tier2} \
	  --binary-name bootstrap \
	  --region $${AWS_REGION:-us-east-1} \
	  --iam-role $${LAMBDA_ROLE:?Set LAMBDA_ROLE} \
	  --timeout 30 \
	  --memory-size 512 \
	  --s3-bucket $${LAMBDA_S3_BUCKET:?Set LAMBDA_S3_BUCKET} \
	  --enable-function-url \
	  --include models/toxicity \
	  --env-var GATEWAY_REGION=$${GATEWAY_REGION:-us-east-1} \
	  --env-var GATEWAY_PLATFORM="AWS Lambda" \
	  --env-var ML_MODEL_PATH=/var/task/models/toxicity
