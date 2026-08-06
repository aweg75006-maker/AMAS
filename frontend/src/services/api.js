const API_BASE = "http://localhost:8000/api";
const SESSION_STORAGE_KEY = "iris_session_id";

function generateUUID() {
  return crypto.randomUUID?.() || `local_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

async function parseError(response, fallback) {
  try {
    const body = await response.json();
    return body?.error?.message || body?.detail || fallback;
  } catch {
    return fallback;
  }
}

export async function getOrCreateSessionId() {
  const existing = localStorage.getItem(SESSION_STORAGE_KEY);
  if (existing) return existing;
  const response = await fetch(`${API_BASE}/sessions`, { method: "POST" });
  const sessionId = response.ok ? (await response.json()).session_id : generateUUID();
  localStorage.setItem(SESSION_STORAGE_KEY, sessionId);
  return sessionId;
}

export function getCurrentSessionId() {
  return localStorage.getItem(SESSION_STORAGE_KEY);
}

export async function clearSession() {
  localStorage.removeItem(SESSION_STORAGE_KEY);
}

export async function getSessionInfo(sessionId) {
  const response = await fetch(`${API_BASE}/sessions/${sessionId}`);
  if (!response.ok) throw new Error(await parseError(response, "会话不存在"));
  return response.json();
}

export async function uploadFiles(files, knowledgeBaseId = null) {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  if (knowledgeBaseId) formData.append("knowledge_base_id", knowledgeBaseId);
  const response = await fetch(`${API_BASE}/upload`, { method: "POST", body: formData });
  if (!response.ok) throw new Error(await parseError(response, "Upload failed"));
  return response.json();
}

export async function listKnowledgeBases() {
  const response = await fetch(`${API_BASE}/knowledge-bases`);
  if (!response.ok) throw new Error(await parseError(response, "Failed to load knowledge bases"));
  return response.json();
}

export async function listKnowledgeBaseDocuments(knowledgeBaseId) {
  const response = await fetch(`${API_BASE}/knowledge-bases/${knowledgeBaseId}/documents`);
  if (!response.ok) throw new Error(await parseError(response, "Failed to load knowledge base documents"));
  return response.json();
}

export async function clearContext(knowledgeBaseId = null) {
  const suffix = knowledgeBaseId ? `?knowledge_base_id=${encodeURIComponent(knowledgeBaseId)}` : "";
  const response = await fetch(`${API_BASE}/clear${suffix}`, { method: "POST" });
  if (!response.ok) throw new Error(await parseError(response, "Failed to clear context"));
  return response.json();
}

async function streamSse(url, body, onData, onDone, onError, onSession) {
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(await parseError(response, "Chat request failed"));

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let paused = false;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const payload = line.slice(6).trim();
        if (payload === "[DONE]") return onDone();
        try {
          const event = JSON.parse(payload);
          if (event.step === "__session__") onSession?.(event.data);
          else if (event.step === "__error__") onError?.(new Error(event.data.message));
          else {
            if (event.step === "__hitl_pause__") paused = true;
            onData(event);
          }
        } catch {}
      }
    }
    if (!paused) onDone();
  } catch (error) {
    onError(error);
  }
}

export async function streamChat(query, searchMode, onData, onDone, onError, onSession, sessionId, knowledgeBaseId = null, hitlPauseBefore = null) {
  const activeSessionId = sessionId || await getOrCreateSessionId();
  return streamSse(
    `${API_BASE}/chat`,
    {
      query,
      search_mode: searchMode,
      session_id: activeSessionId,
      knowledge_base_id: knowledgeBaseId,
      hitl_pause_before: hitlPauseBefore || null,
    },
    onData,
    onDone,
    onError,
    onSession,
  );
}

export async function resumeChat(threadId, humanInput, onData, onDone, onError, onSession) {
  return streamSse(
    `${API_BASE}/chat/resume`,
    { thread_id: threadId, human_input: humanInput },
    onData,
    onDone,
    onError,
    onSession,
  );
}
