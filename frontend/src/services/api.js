// frontend/src/services/api.js

const API_BASE = "http://localhost:8000/api";
const AUTH_TOKEN_KEY = 'iris_access_token';

function contextHeaders(baseHeaders = {}) {
    const headers = { ...baseHeaders };
    const token = localStorage.getItem(AUTH_TOKEN_KEY) || '';
    if (token) {
        headers.Authorization = `Bearer ${token}`;
        return headers;
    }
    const TENANT_ID = localStorage.getItem('iris_tenant_id') || '';
    const USER_ID = localStorage.getItem('iris_user_id') || '';
    if (TENANT_ID) headers['X-Tenant-ID'] = TENANT_ID;
    if (USER_ID) headers['X-User-ID'] = USER_ID;
    return headers;
}

async function parseError(response, fallbackMessage) {
    try {
        const errorData = await response.json();
        return errorData?.error?.message || errorData?.detail || fallbackMessage;
    } catch (e) {
        return fallbackMessage;
    }
}

// ─── UUID 生成（向后兼容）───
function generateUUID() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
      var r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8);
      return v.toString(16);
  });
}

// 本地 thread_id：LangGraph 粒度，每次页面刷新重置
const SESSION_THREAD_ID = generateUUID();

// ─── 服务端会话管理（Phase 1 新增）───
const SESSION_STORAGE_KEY = "iris_session_id";

/**
 * 获取或创建服务端会话 ID。
 * 优先从 localStorage 读取，不存在则请求服务端创建。
 * @returns {Promise<string>} session_id
 */
export async function getOrCreateSessionId() {
  // 1. 先查 localStorage
  let sessionId = localStorage.getItem(SESSION_STORAGE_KEY);
  if (sessionId) {
    return sessionId;
  }

  // 2. 请求服务端创建新会话
  try {
    const response = await fetch(`${API_BASE}/sessions`, {
      method: "POST",
    });
    if (response.ok) {
      const data = await response.json();
      sessionId = data.session_id;
      localStorage.setItem(SESSION_STORAGE_KEY, sessionId);
      console.log("[IRIS] 新会话已创建:", sessionId);
      return sessionId;
    }
  } catch (e) {
    console.warn("[IRIS] 无法连接服务端创建会话，使用本地 UUID:", e);
  }

  // 3. 兜底：本地生成
  sessionId = "local_" + generateUUID();
  localStorage.setItem(SESSION_STORAGE_KEY, sessionId);
  return sessionId;
}

/**
 * 获取当前存储的会话 ID（同步，不发起网络请求）。
 */
export function getCurrentSessionId() {
  return localStorage.getItem(SESSION_STORAGE_KEY) || null;
}

/**
 * 清除会话（开始新对话）。
 */
export async function clearSession() {
  localStorage.removeItem(SESSION_STORAGE_KEY);
}

/**
 * 获取会话详情。
 * @param {string} sessionId
 */
export async function getSessionInfo(sessionId) {
  const response = await fetch(`${API_BASE}/sessions/${sessionId}`);
  if (!response.ok) {
    throw new Error("会话不存在");
  }
  return await response.json();
}

export async function login(username, password) {
  const response = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!response.ok) {
    throw new Error(await parseError(response, "Login failed"));
  }
  const data = await response.json();
  if (data.access_token) {
    localStorage.setItem(AUTH_TOKEN_KEY, data.access_token);
    localStorage.setItem('iris_user_id', data.user?.user_id || '');
    localStorage.setItem('iris_tenant_id', data.active_tenant_id || '');
    localStorage.setItem('iris_username', data.user?.username || '');
    localStorage.setItem('iris_role', data.role || '');
  }
  return data;
}

export function logout() {
  localStorage.removeItem(AUTH_TOKEN_KEY);
  localStorage.removeItem('iris_user_id');
  localStorage.removeItem('iris_tenant_id');
  localStorage.removeItem('iris_username');
  localStorage.removeItem('iris_role');
}

export function hasAuthToken() {
  return Boolean(localStorage.getItem(AUTH_TOKEN_KEY));
}

export async function listMembers() {
  const response = await fetch(`${API_BASE}/members`, {
    headers: contextHeaders(),
  });
  if (!response.ok) {
    throw new Error(await parseError(response, "Failed to load members"));
  }
  return await response.json();
}

export async function inviteMember({ username, email, display_name = '', role = 'member' }) {
  const response = await fetch(`${API_BASE}/members`, {
    method: "POST",
    headers: contextHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ username, email, display_name, role }),
  });
  if (!response.ok) {
    throw new Error(await parseError(response, "Failed to invite member"));
  }
  return await response.json();
}

export async function updateMemberRole(userId, role) {
  const response = await fetch(`${API_BASE}/members/${userId}/role`, {
    method: "PATCH",
    headers: contextHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ role }),
  });
  if (!response.ok) {
    throw new Error(await parseError(response, "Failed to update member role"));
  }
  return await response.json();
}

export async function disableMember(userId) {
  const response = await fetch(`${API_BASE}/members/${userId}/disable`, {
    method: "POST",
    headers: contextHeaders(),
  });
  if (!response.ok) {
    throw new Error(await parseError(response, "Failed to disable member"));
  }
  return await response.json();
}

export async function listAuditLogs({ limit = 100, action = '', actor_user_id = '' } = {}) {
  const params = new URLSearchParams();
  params.set('limit', String(limit));
  if (action) params.set('action', action);
  if (actor_user_id) params.set('actor_user_id', actor_user_id);

  const response = await fetch(`${API_BASE}/audit-logs?${params.toString()}`, {
    headers: contextHeaders(),
  });
  if (!response.ok) {
    throw new Error(await parseError(response, "Failed to load audit logs"));
  }
  return await response.json();
}

export async function listHistorySessions({ limit = 50, scope = 'mine' } = {}) {
  const params = new URLSearchParams();
  params.set('limit', String(limit));
  params.set('scope', scope);

  const response = await fetch(`${API_BASE}/history/sessions?${params.toString()}`, {
    headers: contextHeaders(),
  });
  if (!response.ok) {
    throw new Error(await parseError(response, "Failed to load history sessions"));
  }
  return await response.json();
}

export async function getHistorySession(sessionId, { limit = 50 } = {}) {
  const params = new URLSearchParams();
  params.set('limit', String(limit));

  const response = await fetch(`${API_BASE}/history/sessions/${sessionId}?${params.toString()}`, {
    headers: contextHeaders(),
  });
  if (!response.ok) {
    throw new Error(await parseError(response, "Failed to load history session"));
  }
  return await response.json();
}

export async function listWorkflowRuns({ limit = 50 } = {}) {
  const params = new URLSearchParams();
  params.set('limit', String(limit));

  const response = await fetch(`${API_BASE}/workflow-runs?${params.toString()}`, {
    headers: contextHeaders(),
  });
  if (!response.ok) {
    throw new Error(await parseError(response, "Failed to load workflow runs"));
  }
  return await response.json();
}

export async function getWorkflowRun(runId) {
  const response = await fetch(`${API_BASE}/workflow-runs/${runId}`, {
    headers: contextHeaders(),
  });
  if (!response.ok) {
    throw new Error(await parseError(response, "Failed to load workflow run"));
  }
  return await response.json();
}

export async function listErrorEvents({ limit = 50 } = {}) {
  const params = new URLSearchParams();
  params.set('limit', String(limit));

  const response = await fetch(`${API_BASE}/error-events?${params.toString()}`, {
    headers: contextHeaders(),
  });
  if (!response.ok) {
    throw new Error(await parseError(response, "Failed to load error events"));
  }
  return await response.json();
}

// ─── 文件上传 ───

/**
 * 批量上传文件
 * @param {Array<File>} files - 文件对象数组
 */
export async function uploadFiles(files, knowledgeBaseId = null) {
    const formData = new FormData();
    files.forEach(file => {
        formData.append('files', file);
    });
    if (knowledgeBaseId) {
        formData.append('knowledge_base_id', knowledgeBaseId);
    }

    const response = await fetch(`${API_BASE}/upload`, {
        method: "POST",
        headers: contextHeaders(),
        body: formData
    });

    if (!response.ok) {
        throw new Error(await parseError(response, "Upload failed"));
    }

    return await response.json();
}

export async function listKnowledgeBases() {
  const response = await fetch(`${API_BASE}/knowledge-bases`, {
    headers: contextHeaders(),
  });
  if (!response.ok) {
    throw new Error(await parseError(response, "Failed to load knowledge bases"));
  }
  return await response.json();
}

export async function listKnowledgeBaseDocuments(knowledgeBaseId) {
  const response = await fetch(`${API_BASE}/knowledge-bases/${knowledgeBaseId}/documents`, {
    headers: contextHeaders(),
  });
  if (!response.ok) {
    throw new Error(await parseError(response, "Failed to load knowledge base documents"));
  }
  return await response.json();
}

export async function clearContext(knowledgeBaseId = null) {
  const params = new URLSearchParams();
  if (knowledgeBaseId) {
    params.set('knowledge_base_id', knowledgeBaseId);
  }
  const url = params.toString() ? `${API_BASE}/clear?${params.toString()}` : `${API_BASE}/clear`;
  const response = await fetch(url, {
      method: "POST",
      headers: contextHeaders(),
  });
  if (!response.ok) throw new Error("Failed to clear context");
  return await response.json();
}

// ─── 流式聊天 ───

/**
 * 流式聊天（支持多轮会话）。
 *
 * SSE 事件类型：
 *   { step: "router"|"planner"|"researcher"|"writer"|"reviewer"|"refiner",
 *     data: {...} }
 *   { step: "__session__", data: { session_id, turn_id, ... } }
 *   { step: "__error__", data: { message } }
 *
 * @param {string} query - 问题
 * @param {string} searchMode - 'hybrid' | 'document'
 * @param {string} sessionId - 服务端会话 ID（可选，不传则自动获取）
 * @param {function} onData - 接收消息回调 ({step, data})
 * @param {function} onDone - 完成回调
 * @param {function} onError - 错误回调
 * @param {function} onSession - 会话信息回调（首次返回 session_id）
 */
export async function streamChat(
  query,
  search_mode,
  onData,
  onDone,
  onError,
  onSession,
  sessionId,
  knowledgeBaseId = null
) {
  try {
      // 自动获取或创建会话
      if (!sessionId) {
        sessionId = await getOrCreateSessionId();
      }

      const response = await fetch(`${API_BASE}/chat`, {
          method: 'POST',
          headers: contextHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({
              query: query,
              search_mode: search_mode,
              thread_id: SESSION_THREAD_ID,
              session_id: sessionId,
              knowledge_base_id: knowledgeBaseId,
          }),
      });

      if (!response.ok) throw new Error('Network error');

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop();

          for (const line of lines) {
              const trimmed = line.trim();
              if (!trimmed) continue;

              if (line.startsWith('data: ')) {
                  const dataStr = line.replace('data: ', '').trim();
                  if (dataStr === '[DONE]') {
                      onDone();
                      return;
                  }
                  try {
                      const parsed = JSON.parse(dataStr);

                      // 处理会话信息事件
                      if (parsed.step === '__session__') {
                        if (onSession) {
                          onSession(parsed.data);
                        }
                        // 确保 session_id 已存储
                        if (parsed.data.session_id) {
                          localStorage.setItem(SESSION_STORAGE_KEY, parsed.data.session_id);
                        }
                        continue;
                      }

                      // 处理错误事件
                      if (parsed.step === '__error__') {
                        if (onError) {
                          onError(new Error(parsed.data.message));
                        }
                        continue;
                      }

                      // 正常节点事件
                      onData(parsed);
                  } catch(e) {
                    // 非 JSON 数据，忽略
                  }
              }
          }
      }
  } catch (error) {
    onError(error);
  }
}
