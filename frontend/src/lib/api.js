const API_BASE = '';

export async function moderatePrompt(promptText) {
  const response = await fetch(`${API_BASE}/gateway/moderate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      labels: promptText.split(/\s+/).filter(w => w.length > 0).slice(0, 100),
      nonce: crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(),
      text: promptText,
    }),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const msg = body?.error?.message || body?.detail || 'Moderation failed';
    throw new Error(msg);
  }

  return response.json();
}

export async function checkGatewayHealth() {
  const response = await fetch(`${API_BASE}/gateway/health`);
  if (!response.ok) return null;
  return response.json();
}
