<script>
  import { onMount } from 'svelte';
  import { checkGatewayHealth } from './lib/api.js';
  import PromptTester from './components/PromptTester.svelte';

  let health = null;
  let now = new Date();

  onMount(async () => {
    try {
      health = await checkGatewayHealth();
    } catch {}

    const interval = setInterval(() => { now = new Date(); }, 1000);
    return () => clearInterval(interval);
  });

  $: statusColor = health ? '#22c55e' : '#71717a';
  $: statusText = health ? 'Operational' : 'Checking...';
</script>

<div class="shell">
  <header>
    <div class="header-inner">
      <div class="header-left">
        <div class="status-indicator">
          <span class="status-dot" style="background: {statusColor}"></span>
          <span class="status-label">{statusText}</span>
        </div>
      </div>

      <div class="brand">
        <div class="brand-text">
          <div class="logo">
            <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
              <rect width="28" height="28" rx="8" fill="#6366f1"/>
              <path d="M8 10.5L14 7L20 10.5V17.5L14 21L8 17.5V10.5Z" stroke="white" stroke-width="1.5" fill="none"/>
              <path d="M14 7V21" stroke="white" stroke-width="1.2" opacity="0.5"/>
              <path d="M8 10.5L20 17.5" stroke="white" stroke-width="1.2" opacity="0.5"/>
              <path d="M20 10.5L8 17.5" stroke="white" stroke-width="1.2" opacity="0.5"/>
            </svg>
          </div>
          <h1>WASMnism</h1>
          <span class="brand-sub">WASM-Powered Content Moderation at the Edge</span>
        </div>
      </div>

      <div class="header-right">
        {#if health}
          <div class="header-meta">
            <span class="meta-chip">
              <span class="chip-label">Platform</span>
              <span class="chip-value">{health.platform || 'spin'}</span>
            </span>
            <span class="meta-chip">
              <span class="chip-label">Region</span>
              <span class="chip-value">{health.region || '—'}</span>
            </span>
          </div>
        {/if}
      </div>
    </div>
  </header>

  <main>
    <div class="content-grid">
      <div class="main-col">
        <PromptTester />
      </div>

      <aside class="side-col">
        <div class="card info-card">
          <h3>How It Works</h3>
          <p class="info-desc">Every prompt passes through a moderation pipeline running as WebAssembly at the edge — before reaching any AI model.</p>
          <ol class="pipeline-list">
            <li><span class="step-badge">1</span>Unicode NFC normalization</li>
            <li><span class="step-badge">2</span>SHA-256 content hashing</li>
            <li><span class="step-badge">3</span>Leetspeak expansion</li>
            <li><span class="step-badge">4</span>Prohibited content scan</li>
            <li><span class="step-badge">5</span>PII detection (email, phone, SSN)</li>
            <li><span class="step-badge">6</span>Injection detection (XSS, SQL)</li>
            <li><span class="step-badge">7</span>ML toxicity classifier</li>
            <li><span class="step-badge">8</span>Policy verdict</li>
          </ol>
        </div>

        <div class="card info-card">
          <h3>About This Benchmark</h3>
          <p class="info-desc">This gateway runs identically on Akamai Functions and AWS Lambda. The scorecard measures overhead across both platforms. To access the testing methodology and latest scorecard, <a href="https://github.com/jgdynamite/WASMnism/blob/main/docs/benchmark_contract.md" target="_blank" rel="noopener noreferrer">click here</a>.</p>
          <div class="tech-pills">
            <span class="pill">Rust</span>
            <span class="pill">WASM</span>
            <span class="pill">Tract NNEF</span>
            <span class="pill">MiniLMv2</span>
          </div>
        </div>

        {#if health?.ml_classifier_ready !== undefined}
          <div class="card info-card">
            <h3>ML Model Status</h3>
            <div class="model-status-grid">
              <div class="model-row">
                <span class="model-label">Model file</span>
                <span class="model-val" class:ok={health.ml_model_file} class:err={!health.ml_model_file}>
                  {health.ml_model_file ? 'Loaded' : 'Missing'}
                </span>
              </div>
              <div class="model-row">
                <span class="model-label">Vocabulary</span>
                <span class="model-val" class:ok={health.ml_vocab_file} class:err={!health.ml_vocab_file}>
                  {health.ml_vocab_file ? 'Loaded' : 'Missing'}
                </span>
              </div>
              <div class="model-row">
                <span class="model-label">Classifier</span>
                <span class="model-val" class:ok={health.ml_classifier_ready} class:err={!health.ml_classifier_ready}>
                  {health.ml_classifier_ready ? 'Ready' : 'Standby'}
                </span>
              </div>
            </div>
          </div>
        {/if}
      </aside>
    </div>
  </main>

  <footer>
    <span class="footer-text">WASMnism Edge Gateway Benchmark</span>
    <span class="footer-sep">&middot;</span>
    <span class="footer-text">{now.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })}</span>
  </footer>
</div>

<style>
  :global(*) {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }

  :global(body) {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #09090b;
    color: #fafafa;
    min-height: 100vh;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
  }

  .shell {
    min-height: 100vh;
    display: flex;
    flex-direction: column;
  }

  /* ---- Header ---- */

  header {
    border-bottom: 1px solid #27272a;
    background: rgba(9, 9, 11, 0.8);
    backdrop-filter: blur(12px);
    position: sticky;
    top: 0;
    z-index: 50;
  }

  .header-inner {
    max-width: 1280px;
    margin: 0 auto;
    padding: 0 32px;
    min-height: 64px;
    padding-top: 12px;
    padding-bottom: 12px;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .header-left {
    display: flex;
    align-items: center;
    min-width: 120px;
  }

  .brand {
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .brand-text {
    text-align: center;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
  }

  .logo {
    margin-bottom: 2px;
  }

  .brand-text h1 {
    font-size: 18px;
    font-weight: 700;
    letter-spacing: -0.02em;
    color: #fafafa;
    line-height: 1.2;
  }

  .brand-sub {
    font-size: 12px;
    color: #71717a;
    font-weight: 400;
  }

  .header-right {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    min-width: 120px;
    gap: 20px;
  }

  .header-meta {
    display: flex;
    gap: 8px;
  }

  .meta-chip {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    background: #18181b;
    border: 1px solid #27272a;
    border-radius: 6px;
    font-size: 12px;
  }

  .chip-label {
    color: #52525b;
    font-weight: 500;
  }

  .chip-value {
    color: #a1a1aa;
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
  }

  .status-indicator {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 12px;
    background: #18181b;
    border: 1px solid #27272a;
    border-radius: 20px;
  }

  .status-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  .status-label {
    font-size: 12px;
    font-weight: 500;
    color: #a1a1aa;
  }

  /* ---- Main ---- */

  main {
    flex: 1;
    max-width: 1280px;
    margin: 0 auto;
    padding: 32px;
    width: 100%;
  }

  .content-grid {
    display: grid;
    grid-template-columns: 1fr 340px;
    gap: 24px;
    align-items: start;
  }

  .side-col {
    display: flex;
    flex-direction: column;
    gap: 16px;
    position: sticky;
    top: 96px;
  }

  /* ---- Cards ---- */

  .card {
    background: #18181b;
    border: 1px solid #27272a;
    border-radius: 12px;
    padding: 24px;
  }

  .info-card h3 {
    font-size: 13px;
    font-weight: 600;
    color: #e4e4e7;
    margin-bottom: 10px;
    letter-spacing: -0.01em;
  }

  .info-desc {
    font-size: 13px;
    line-height: 1.6;
    color: #71717a;
    margin-bottom: 16px;
  }

  .info-desc a {
    color: #6366f1;
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  .info-desc a:hover {
    color: #818cf8;
  }

  .pipeline-list {
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .pipeline-list li {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 13px;
    color: #a1a1aa;
  }

  .step-badge {
    width: 22px;
    height: 22px;
    border-radius: 6px;
    background: rgba(99, 102, 241, 0.12);
    color: #818cf8;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 11px;
    font-weight: 600;
    flex-shrink: 0;
  }

  .tech-pills {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .pill {
    padding: 3px 10px;
    border-radius: 20px;
    background: rgba(99, 102, 241, 0.08);
    border: 1px solid rgba(99, 102, 241, 0.15);
    color: #a5b4fc;
    font-size: 11px;
    font-weight: 500;
  }

  .model-status-grid {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .model-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .model-label {
    font-size: 13px;
    color: #71717a;
  }

  .model-val {
    font-size: 12px;
    font-weight: 500;
    font-family: 'JetBrains Mono', monospace;
  }

  .model-val.ok { color: #4ade80; }
  .model-val.err { color: #71717a; }

  /* ---- Footer ---- */

  footer {
    border-top: 1px solid #27272a;
    padding: 16px 32px;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
  }

  .footer-text {
    font-size: 12px;
    color: #3f3f46;
  }

  .footer-sep {
    color: #27272a;
  }

  /* ---- Responsive ---- */

  @media (max-width: 1024px) {
    .content-grid {
      grid-template-columns: 1fr;
    }
    .side-col {
      position: static;
    }
    .header-meta {
      display: none;
    }
  }

  @media (max-width: 640px) {
    .header-inner {
      padding: 0 16px;
    }
    main {
      padding: 16px;
    }
  }
</style>
