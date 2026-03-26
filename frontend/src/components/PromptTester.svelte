<script>
  import { moderatePrompt } from '../lib/api.js';
  import ResultPanel from './ResultPanel.svelte';

  let prompt = '';
  let loading = false;
  let error = null;
  let result = null;
  let roundTripMs = null;
  let history = [];

  const examples = [
    { label: 'Friendly greeting', text: 'Hello! How are you doing today? I hope you\'re having a great day.', expect: 'allow' },
    { label: 'Semantic toxicity', text: 'You are the most pathetic disgusting excuse for a human being, go rot in a ditch', expect: 'block' },
    { label: 'XSS injection', text: 'Show me a cat \x3Cscript\x3Ealert(document.cookie)\x3C/script\x3E', expect: 'block' },
    { label: 'SQL injection', text: "Generate a dog'; DROP TABLE users;--", expect: 'block' },
    { label: 'PII leakage', text: 'Send the result to john@company.com or call 555-867-5309', expect: 'review' },
    { label: 'Subtle hostility', text: 'I really hope terrible things happen to you and everyone you love', expect: 'block' },
    { label: 'Leetspeak evasion', text: 'Make an image of h@t3 and k1ll and @bus3', expect: 'review' },
    { label: 'Safe creative', text: 'Write a poem about autumn leaves falling gently onto a quiet forest path', expect: 'allow' },
  ];

  async function submit() {
    if (!prompt.trim() || loading) return;
    loading = true;
    error = null;
    result = null;
    roundTripMs = null;

    const start = performance.now();
    try {
      result = await moderatePrompt(prompt.trim());
      roundTripMs = performance.now() - start;
      history = [
        { prompt: prompt.trim(), verdict: result.verdict, ms: roundTripMs, timestamp: Date.now() },
        ...history.slice(0, 9),
      ];
    } catch (e) {
      error = e.message;
      roundTripMs = performance.now() - start;
    } finally {
      loading = false;
    }
  }

  function useExample(ex) {
    prompt = ex.text;
    submit();
  }

  function handleKeydown(e) {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      submit();
    }
  }

  function clearResult() {
    result = null;
    error = null;
    roundTripMs = null;
  }
</script>

<div class="tester">
  <div class="card input-card">
    <div class="card-header">
      <h2>Test a Prompt</h2>
      <p class="card-desc">Enter a prompt as if sending it to a generative AI. The edge firewall evaluates it in real time.</p>
    </div>

    <div class="examples">
      <span class="examples-label">Examples</span>
      <div class="example-chips">
        {#each examples as ex}
          <button
            class="example-chip"
            class:allow={ex.expect === 'allow'}
            class:block={ex.expect === 'block'}
            class:review={ex.expect === 'review'}
            on:click={() => useExample(ex)}
            disabled={loading}
          >
            {ex.label}
          </button>
        {/each}
      </div>
    </div>

    <div class="input-group">
      <textarea
        bind:value={prompt}
        on:keydown={handleKeydown}
        placeholder="Type or paste a prompt to evaluate..."
        rows="4"
        disabled={loading}
        class:has-value={prompt.length > 0}
      ></textarea>
      <div class="input-actions">
        <div class="input-meta">
          <span class="char-counter" class:over={prompt.length > 2000}>
            {prompt.length}<span class="char-max"> / 2000</span>
          </span>
          <span class="shortcut">&#8984;+Enter</span>
        </div>
        <button class="submit-btn" on:click={submit} disabled={loading || !prompt.trim()}>
          {#if loading}
            <span class="spinner"></span>
            Evaluating
          {:else}
            Evaluate Prompt
          {/if}
        </button>
      </div>
    </div>
  </div>

  {#if error}
    <div class="card error-card">
      <div class="error-header">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
          <circle cx="8" cy="8" r="7" stroke="#ef4444" stroke-width="1.5" fill="none"/>
          <path d="M8 4.5V8.5M8 10.5V11" stroke="#ef4444" stroke-width="1.5" stroke-linecap="round"/>
        </svg>
        <span>Request Failed</span>
      </div>
      <p class="error-msg">{error}</p>
      {#if roundTripMs != null}
        <span class="error-timing">after {roundTripMs.toFixed(0)}ms</span>
      {/if}
    </div>
  {/if}

  {#if result}
    <ResultPanel {result} {roundTripMs} />
  {/if}

  {#if history.length > 1}
    <div class="card history-card">
      <h3>Recent Evaluations</h3>
      <div class="history-list">
        {#each history as h, i}
          <div class="history-row" class:current={i === 0}>
            <span class="history-verdict" class:allow={h.verdict === 'allow'} class:block={h.verdict === 'block'} class:review={h.verdict === 'review'}>
              {h.verdict}
            </span>
            <span class="history-prompt">{h.prompt.slice(0, 60)}{h.prompt.length > 60 ? '...' : ''}</span>
            <span class="history-ms">{h.ms.toFixed(0)}ms</span>
          </div>
        {/each}
      </div>
    </div>
  {/if}
</div>

<style>
  .tester {
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

  /* ---- Input Card ---- */

  .card-header {
    margin-bottom: 20px;
  }

  .card-header h2 {
    font-size: 16px;
    font-weight: 600;
    color: #fafafa;
    letter-spacing: -0.01em;
    margin-bottom: 4px;
  }

  .card-desc {
    font-size: 13px;
    color: #71717a;
    line-height: 1.5;
  }

  /* ---- Examples ---- */

  .examples {
    margin-bottom: 16px;
  }

  .examples-label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #52525b;
    display: block;
    margin-bottom: 8px;
  }

  .example-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .example-chip {
    padding: 5px 12px;
    border: 1px solid #3f3f46;
    border-radius: 8px;
    background: transparent;
    color: #a1a1aa;
    font-size: 12px;
    font-family: inherit;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .example-chip:hover:not(:disabled) {
    background: #27272a;
    border-color: #52525b;
    color: #e4e4e7;
  }

  .example-chip:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  .example-chip.allow { border-color: rgba(34, 197, 94, 0.25); color: #86efac; }
  .example-chip.allow:hover:not(:disabled) { background: rgba(34, 197, 94, 0.08); border-color: rgba(34, 197, 94, 0.4); }
  .example-chip.block { border-color: rgba(239, 68, 68, 0.25); color: #fca5a5; }
  .example-chip.block:hover:not(:disabled) { background: rgba(239, 68, 68, 0.08); border-color: rgba(239, 68, 68, 0.4); }
  .example-chip.review { border-color: rgba(234, 179, 8, 0.25); color: #fde047; }
  .example-chip.review:hover:not(:disabled) { background: rgba(234, 179, 8, 0.08); border-color: rgba(234, 179, 8, 0.4); }

  /* ---- Text Input ---- */

  .input-group {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  textarea {
    width: 100%;
    padding: 14px 16px;
    background: #09090b;
    border: 1px solid #3f3f46;
    border-radius: 10px;
    color: #fafafa;
    font-family: 'Inter', sans-serif;
    font-size: 14px;
    line-height: 1.6;
    resize: vertical;
    outline: none;
    transition: border-color 0.2s, box-shadow 0.2s;
    min-height: 100px;
  }

  textarea::placeholder {
    color: #52525b;
  }

  textarea:focus {
    border-color: #6366f1;
    box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.12);
  }

  textarea:disabled {
    opacity: 0.5;
  }

  .input-actions {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .input-meta {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .char-counter {
    font-size: 12px;
    font-family: 'JetBrains Mono', monospace;
    color: #52525b;
  }

  .char-counter.over { color: #ef4444; }
  .char-max { color: #3f3f46; }

  .shortcut {
    font-size: 11px;
    color: #3f3f46;
    padding: 2px 6px;
    border: 1px solid #27272a;
    border-radius: 4px;
    font-family: 'JetBrains Mono', monospace;
  }

  .submit-btn {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 20px;
    background: #6366f1;
    border: none;
    border-radius: 8px;
    color: #fff;
    font-family: 'Inter', sans-serif;
    font-weight: 600;
    font-size: 13px;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .submit-btn:hover:not(:disabled) {
    background: #4f46e5;
  }

  .submit-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  .spinner {
    width: 14px;
    height: 14px;
    border: 2px solid rgba(255, 255, 255, 0.3);
    border-top-color: #fff;
    border-radius: 50%;
    animation: spin 0.6s linear infinite;
  }

  @keyframes spin {
    to { transform: rotate(360deg); }
  }

  /* ---- Error ---- */

  .error-card {
    border-color: rgba(239, 68, 68, 0.3);
    background: rgba(239, 68, 68, 0.04);
  }

  .error-header {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    font-weight: 600;
    color: #fca5a5;
    margin-bottom: 6px;
  }

  .error-msg {
    font-size: 13px;
    color: #a1a1aa;
    line-height: 1.5;
  }

  .error-timing {
    font-size: 11px;
    color: #52525b;
    font-family: 'JetBrains Mono', monospace;
    margin-top: 6px;
    display: block;
  }

  /* ---- History ---- */

  .history-card h3 {
    font-size: 13px;
    font-weight: 600;
    color: #e4e4e7;
    margin-bottom: 12px;
  }

  .history-list {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .history-row {
    display: grid;
    grid-template-columns: 60px 1fr 56px;
    gap: 12px;
    align-items: center;
    padding: 6px 10px;
    border-radius: 6px;
    transition: background 0.1s;
  }

  .history-row.current {
    background: rgba(99, 102, 241, 0.06);
  }

  .history-verdict {
    font-size: 11px;
    font-weight: 600;
    font-family: 'JetBrains Mono', monospace;
    text-transform: uppercase;
  }

  .history-verdict.allow { color: #4ade80; }
  .history-verdict.block { color: #f87171; }
  .history-verdict.review { color: #facc15; }

  .history-prompt {
    font-size: 12px;
    color: #71717a;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .history-ms {
    font-size: 11px;
    font-family: 'JetBrains Mono', monospace;
    color: #52525b;
    text-align: right;
  }
</style>
