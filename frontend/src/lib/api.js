/**
 * API client for the Lenny Growth Assistant backend.
 *
 * DECISION: Thin fetch wrapper over axios
 *   Axios adds 13KB for features we don't need (interceptors, progress,
 *   Node.js support). fetch() is built into every modern browser.
 *   Our wrapper adds JSON parsing, error handling, and base URL config.
 */

const API_BASE = import.meta.env.VITE_API_URL || '';

async function request(path, options = {}) {
  const url = `${API_BASE}${path}`;
  const config = {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  };

  const response = await fetch(url, config);

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || error.error || `Request failed: ${response.status}`);
  }

  // Handle 204 No Content (e.g., DELETE)
  if (response.status === 204) return null;
  return response.json();
}

// --- Sessions ---

export async function createSession(title = null) {
  return request('/api/v1/sessions', {
    method: 'POST',
    body: JSON.stringify({ title, metadata: {} }),
  });
}

export async function listSessions(limit = 20, offset = 0) {
  return request(`/api/v1/sessions?limit=${limit}&offset=${offset}`);
}

export async function getSession(sessionId) {
  return request(`/api/v1/sessions/${sessionId}`);
}

export async function deleteSession(sessionId) {
  return request(`/api/v1/sessions/${sessionId}`, { method: 'DELETE' });
}

// --- Chat ---

export async function getMessages(sessionId) {
  return request(`/api/v1/sessions/${sessionId}/messages`);
}

export async function sendMessage(sessionId, content) {
  return request(`/api/v1/sessions/${sessionId}/chat`, {
    method: 'POST',
    body: JSON.stringify({ content }),
  });
}

// --- Knowledge Base ---

export async function searchKnowledge(query, topK = 5) {
  return request(`/api/v1/knowledge/search?q=${encodeURIComponent(query)}&top_k=${topK}`);
}

export async function getKnowledgeStats() {
  return request('/api/v1/knowledge/stats');
}

// --- System ---

export async function getHealth() {
  return request('/health');
}

export async function getModelConfig() {
  return request('/config/model');
}

export async function listProviders() {
  return request('/config/providers');
}

export async function switchProvider(provider, model = null) {
  return request('/config/model/switch', {
    method: 'POST',
    body: JSON.stringify({ provider, model }),
  });
}
