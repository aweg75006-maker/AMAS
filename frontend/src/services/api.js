// frontend/src/services/api.js

const API_BASE = "http://localhost:8000/api";

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

// ─── 文件上传 ───

/**
 * 批量上传文件
 * @param {Array<File>} files - 文件对象数组
 */
export async function uploadFiles(files) {
    const formData = new FormData();
    files.forEach(file => {
        formData.append('files', file);
    });

    const response = await fetch(`${API_BASE}/upload`, {
        method: "POST",
        body: formData
    });

    if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "Upload failed");
    }

    return await response.json();
}

export async function clearContext() {
  const response = await fetch(`${API_BASE}/clear`, {
      method: "POST"
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
  sessionId
) {
  try {
      // 自动获取或创建会话
      if (!sessionId) {
        sessionId = await getOrCreateSessionId();
      }

      const response = await fetch(`${API_BASE}/chat`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
              query: query,
              search_mode: search_mode,
              thread_id: SESSION_THREAD_ID,
              session_id: sessionId,
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
