<script>
  export let result = null;
  export let roundTripMs = null;

  $: verdict = result?.verdict;
  $: info = result?.moderation;
  $: cache = result?.cache;
  $: gateway = result?.gateway;
  $: ml = info?.ml_toxicity;

  $: hasRuleFlags = info?.policy_flags?.some(f => f !== 'ml_toxicity_detected') && info?.policy_flags?.length > 0;
  $: hasMlFlag = info?.policy_flags?.includes('ml_toxicity_detected');
  $: rulesBlocked = verdict === 'block' && !hasMlFlag && hasRuleFlags;

  function verdictMeta(v) {
    if (v === 'allow') return { label: 'Allowed', color: '#22c55e', bg: 'rgba(34, 197, 94, 0.08)', border: 'rgba(34, 197, 94, 0.2)', icon: '&#10003;' };
    if (v === 'review') return { label: 'Review', color: '#eab308', bg: 'rgba(234, 179, 8, 0.08)', border: 'rgba(234, 179, 8, 0.2)', icon: '&#9888;' };
    if (v === 'block') return { label: 'Blocked', color: '#ef4444', bg: 'rgba(239, 68, 68, 0.08)', border: 'rgba(239, 68, 68, 0.2)', icon: '&#10005;' };
    return { label: v, color: '#71717a', bg: '#18181b', border: '#27272a', icon: '?' };
  }

  $: vm = verdictMeta(verdict);

  const pipelineSteps = [
    { key: 'normalize', label: 'Normalize', num: '1' },
    { key: 'hash', label: 'Hash', num: '2' },
    { key: 'rules', label: 'Rules', num: '3' },
    { key: 'ml', label: 'ML Model', num: '4' },
    { key: 'verdict', label: 'Verdict', num: '5' },
  ];

  function stepState(step) {
    if (step.key === 'normalize' || step.key === 'hash') return 'done';
    if (step.key === 'rules') return hasRuleFlags ? 'flagged' : 'done';
    if (step.key === 'ml') {
      if (!ml) return 'skipped';
      if (hasMlFlag) return 'flagged';
      return 'done';
    }
    if (step.key === 'verdict') {
      if (verdict === 'allow') return 'done';
      if (verdict === 'review') return 'warning';
      return 'flagged';
    }
    return 'done';
  }

  function formatScore(s) {
    if (s >= 0.01) return (s * 100).toFixed(1) + '%';
    return '<0.1%';
  }

  function toxicLevel(score, threshold) {
    if (score >= threshold) return 'danger';
    if (score >= threshold * 0.6) return 'warning';
    return 'safe';
  }
</script>

{#if result}
<div class="results">
  <!-- Verdict Banner -->
  <div class="card verdict-card" style="border-color: {vm.border}; background: {vm.bg}">
    <div class="verdict-row">
      <div class="verdict-badge" style="background: {vm.color}">
        <span class="verdict-icon">{@html vm.icon}</span>
      </div>
      <div class="verdict-info">
        <span class="verdict-label" style="color: {vm.color}">{vm.label}</span>
        <span class="verdict-sub">
          {#if verdict === 'allow'}
            Prompt is safe to forward to the AI model
          {:else if verdict === 'review'}
            Prompt flagged for human review
          {:else}
            Prompt blocked by the firewall
          {/if}
        </span>
      </div>
      <div class="verdict-timing">
        {#if roundTripMs != null}
          <div class="timing-item">
            <span class="timing-num">{roundTripMs.toFixed(0)}</span>
            <span class="timing-unit">ms round-trip</span>
          </div>
        {/if}
        {#if info?.processing_ms != null}
          <div class="timing-item">
            <span class="timing-num">{info.processing_ms.toFixed(0)}</span>
            <span class="timing-unit">ms gateway</span>
          </div>
        {/if}
      </div>
    </div>
  </div>

  <!-- Pipeline Visualization -->
  <div class="card pipeline-card">
    <h3>Pipeline</h3>
    <div class="pipeline">
      {#each pipelineSteps as step, i}
        {#if i > 0}
          <div class="pipe-connector">
            <div class="pipe-line"></div>
          </div>
        {/if}
        <div class="pipe-step {stepState(step)}">
          <span class="pipe-num">{step.num}</span>
          <span class="pipe-label">{step.label}</span>
          {#if step.key === 'ml' && ml}
            <span class="pipe-detail">{ml.inference_ms.toFixed(0)}ms</span>
          {/if}
          {#if step.key === 'ml' && !ml}
            <span class="pipe-detail">skipped</span>
          {/if}
        </div>
      {/each}
    </div>
  </div>

  <!-- Two-column detail area -->
  <div class="detail-grid">
    <!-- Left: ML Toxicity -->
    <div class="card">
      <h3>ML Toxicity Analysis</h3>
      {#if ml}
        <div class="gauges">
          <div class="gauge-row">
            <div class="gauge-header">
              <span class="gauge-label">Toxic</span>
              <span class="gauge-value {toxicLevel(ml.toxic, 0.65)}">{formatScore(ml.toxic)}</span>
            </div>
            <div class="gauge-track">
              <div class="gauge-fill {toxicLevel(ml.toxic, 0.65)}" style="width: {Math.max(ml.toxic * 100, 0.5)}%"></div>
              <div class="gauge-threshold" style="left: 65%">
                <span class="threshold-label">65%</span>
              </div>
            </div>
          </div>

          <div class="gauge-row">
            <div class="gauge-header">
              <span class="gauge-label">Severe Toxic</span>
              <span class="gauge-value {toxicLevel(ml.severe_toxic, 0.45)}">{formatScore(ml.severe_toxic)}</span>
            </div>
            <div class="gauge-track">
              <div class="gauge-fill {toxicLevel(ml.severe_toxic, 0.45)}" style="width: {Math.max(ml.severe_toxic * 100, 0.5)}%"></div>
              <div class="gauge-threshold" style="left: 45%">
                <span class="threshold-label">45%</span>
              </div>
            </div>
          </div>
        </div>

        <div class="ml-footer">
          <span class="ml-model">{ml.model}</span>
          <span class="ml-time">{ml.inference_ms.toFixed(0)}ms inference</span>
        </div>
      {:else}
        <div class="empty-state">
          <span class="empty-icon">
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
              <path d="M10 4V10L14 12" stroke="#52525b" stroke-width="1.5" stroke-linecap="round"/>
              <circle cx="10" cy="10" r="8" stroke="#3f3f46" stroke-width="1.5" fill="none"/>
            </svg>
          </span>
          <span class="empty-text">ML inference was skipped — rules already blocked this prompt.</span>
        </div>
      {/if}
    </div>

    <!-- Right: Flags & Metadata -->
    <div class="card">
      <h3>Details</h3>

      {#if info?.policy_flags?.length > 0}
        <div class="detail-section">
          <span class="detail-label">Policy Flags</span>
          <div class="tag-row">
            {#each info.policy_flags as flag}
              <span class="tag flag-tag">{flag.replace(/_/g, ' ')}</span>
            {/each}
          </div>
        </div>
      {/if}

      {#if info?.blocked_terms?.length > 0}
        <div class="detail-section">
          <span class="detail-label">Matched Terms</span>
          <div class="tag-row">
            {#each info.blocked_terms as term}
              <span class="tag term-tag">{term}</span>
            {/each}
          </div>
        </div>
      {/if}

      <div class="detail-section">
        <span class="detail-label">Metadata</span>
        <div class="meta-grid">
          {#if cache}
            <div class="meta-pair">
              <span class="mk">Cache</span>
              <span class="mv" class:hit={cache.hit}>{cache.hit ? 'Hit' : 'Miss'}</span>
            </div>
          {/if}
          {#if info?.confidence != null}
            <div class="meta-pair">
              <span class="mk">Confidence</span>
              <span class="mv">{(info.confidence * 100).toFixed(0)}%</span>
            </div>
          {/if}
          {#if gateway?.platform}
            <div class="meta-pair">
              <span class="mk">Platform</span>
              <span class="mv accent">{gateway.platform}</span>
            </div>
          {/if}
          {#if gateway?.region}
            <div class="meta-pair">
              <span class="mk">Region</span>
              <span class="mv">{gateway.region}</span>
            </div>
          {/if}
          {#if gateway?.request_id}
            <div class="meta-pair full">
              <span class="mk">Request ID</span>
              <code class="mv mono">{gateway.request_id.slice(0, 18)}...</code>
            </div>
          {/if}
          {#if cache?.hash}
            <div class="meta-pair full">
              <span class="mk">Content Hash</span>
              <code class="mv mono">{cache.hash.slice(0, 28)}...</code>
            </div>
          {/if}
        </div>
      </div>
    </div>
  </div>
</div>
{/if}

<style>
  .results {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  .card {
    background: #18181b;
    border: 1px solid #27272a;
    border-radius: 12px;
    padding: 24px;
  }

  .card h3 {
    font-size: 13px;
    font-weight: 600;
    color: #a1a1aa;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-bottom: 16px;
  }

  /* ---- Verdict Banner ---- */

  .verdict-card {
    padding: 20px 24px;
  }

  .verdict-row {
    display: flex;
    align-items: center;
    gap: 16px;
  }

  .verdict-badge {
    width: 40px;
    height: 40px;
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }

  .verdict-icon {
    color: #fff;
    font-size: 18px;
    font-weight: 700;
    line-height: 1;
  }

  .verdict-info {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .verdict-label {
    font-size: 16px;
    font-weight: 700;
    letter-spacing: -0.01em;
  }

  .verdict-sub {
    font-size: 13px;
    color: #71717a;
  }

  .verdict-timing {
    display: flex;
    gap: 16px;
    flex-shrink: 0;
  }

  .timing-item {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
  }

  .timing-num {
    font-size: 18px;
    font-weight: 700;
    font-family: 'JetBrains Mono', monospace;
    color: #e4e4e7;
    line-height: 1.2;
  }

  .timing-unit {
    font-size: 10px;
    color: #52525b;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  /* ---- Pipeline ---- */

  .pipeline-card {
    padding: 20px 24px;
  }

  .pipeline {
    display: flex;
    align-items: center;
  }

  .pipe-step {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 14px;
    border-radius: 8px;
    border: 1px solid #3f3f46;
    background: #09090b;
    flex-shrink: 0;
    transition: all 0.2s;
  }

  .pipe-step.done {
    border-color: rgba(34, 197, 94, 0.3);
    background: rgba(34, 197, 94, 0.05);
  }

  .pipe-step.flagged {
    border-color: rgba(239, 68, 68, 0.4);
    background: rgba(239, 68, 68, 0.06);
  }

  .pipe-step.warning {
    border-color: rgba(234, 179, 8, 0.3);
    background: rgba(234, 179, 8, 0.05);
  }

  .pipe-step.skipped {
    opacity: 0.4;
  }

  .pipe-num {
    width: 20px;
    height: 20px;
    border-radius: 5px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 11px;
    font-weight: 700;
    background: #27272a;
    color: #71717a;
    flex-shrink: 0;
  }

  .pipe-step.done .pipe-num { background: rgba(34, 197, 94, 0.15); color: #4ade80; }
  .pipe-step.flagged .pipe-num { background: rgba(239, 68, 68, 0.15); color: #f87171; }
  .pipe-step.warning .pipe-num { background: rgba(234, 179, 8, 0.15); color: #facc15; }

  .pipe-label {
    font-size: 12px;
    font-weight: 500;
    color: #a1a1aa;
    white-space: nowrap;
  }

  .pipe-step.done .pipe-label { color: #86efac; }
  .pipe-step.flagged .pipe-label { color: #fca5a5; }
  .pipe-step.warning .pipe-label { color: #fde047; }

  .pipe-detail {
    font-size: 10px;
    font-family: 'JetBrains Mono', monospace;
    color: #52525b;
    margin-left: -2px;
  }

  .pipe-connector {
    flex: 1;
    min-width: 12px;
    max-width: 40px;
    display: flex;
    align-items: center;
    padding: 0 2px;
  }

  .pipe-line {
    height: 1px;
    width: 100%;
    background: #3f3f46;
  }

  /* ---- Detail Grid ---- */

  .detail-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
  }

  @media (max-width: 768px) {
    .detail-grid {
      grid-template-columns: 1fr;
    }
    .verdict-row {
      flex-wrap: wrap;
    }
    .verdict-timing {
      width: 100%;
      justify-content: flex-start;
      margin-top: 8px;
      padding-top: 8px;
      border-top: 1px solid rgba(255,255,255,0.05);
    }
    .pipeline {
      flex-wrap: wrap;
      gap: 6px;
    }
    .pipe-connector {
      display: none;
    }
  }

  /* ---- Toxicity Gauges ---- */

  .gauges {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  .gauge-row {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .gauge-header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
  }

  .gauge-label {
    font-size: 13px;
    font-weight: 500;
    color: #a1a1aa;
  }

  .gauge-value {
    font-size: 14px;
    font-weight: 600;
    font-family: 'JetBrains Mono', monospace;
  }

  .gauge-value.safe { color: #4ade80; }
  .gauge-value.warning { color: #facc15; }
  .gauge-value.danger { color: #f87171; }

  .gauge-track {
    height: 8px;
    background: #09090b;
    border-radius: 4px;
    position: relative;
    overflow: visible;
  }

  .gauge-fill {
    height: 100%;
    border-radius: 4px;
    transition: width 0.5s ease;
    min-width: 3px;
  }

  .gauge-fill.safe { background: linear-gradient(90deg, #22c55e, #4ade80); }
  .gauge-fill.warning { background: linear-gradient(90deg, #eab308, #facc15); }
  .gauge-fill.danger { background: linear-gradient(90deg, #ef4444, #f87171); }

  .gauge-threshold {
    position: absolute;
    top: -3px;
    bottom: -3px;
    width: 1px;
    background: #52525b;
    transform: translateX(-50%);
  }

  .threshold-label {
    position: absolute;
    top: -16px;
    left: 50%;
    transform: translateX(-50%);
    font-size: 9px;
    color: #52525b;
    font-family: 'JetBrains Mono', monospace;
    white-space: nowrap;
  }

  .ml-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 16px;
    padding-top: 12px;
    border-top: 1px solid #27272a;
  }

  .ml-model {
    font-size: 12px;
    color: #52525b;
  }

  .ml-time {
    font-size: 12px;
    font-family: 'JetBrains Mono', monospace;
    color: #818cf8;
  }

  /* ---- Empty State ---- */

  .empty-state {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 12px;
    background: #09090b;
    border-radius: 8px;
  }

  .empty-icon {
    flex-shrink: 0;
    margin-top: 1px;
  }

  .empty-text {
    font-size: 13px;
    color: #52525b;
    line-height: 1.5;
  }

  /* ---- Details Section ---- */

  .detail-section {
    margin-bottom: 16px;
  }

  .detail-section:last-child {
    margin-bottom: 0;
  }

  .detail-label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #52525b;
    display: block;
    margin-bottom: 8px;
  }

  .tag-row {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .tag {
    padding: 3px 10px;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 500;
    font-family: 'JetBrains Mono', monospace;
  }

  .flag-tag {
    background: rgba(234, 179, 8, 0.1);
    border: 1px solid rgba(234, 179, 8, 0.2);
    color: #fde047;
  }

  .term-tag {
    background: rgba(239, 68, 68, 0.1);
    border: 1px solid rgba(239, 68, 68, 0.2);
    color: #fca5a5;
  }

  .meta-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }

  .meta-pair {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 8px 10px;
    background: #09090b;
    border-radius: 6px;
  }

  .meta-pair.full {
    grid-column: 1 / -1;
  }

  .mk {
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #52525b;
  }

  .mv {
    font-size: 13px;
    color: #a1a1aa;
  }

  .mv.hit { color: #4ade80; }
  .mv.accent { color: #818cf8; }
  .mv.mono {
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    color: #71717a;
  }
</style>
