<template>
    <transition name="slide-down">
        <div v-if="showWarning" class="fixed top-24 left-1/2 transform -translate-x-1/2 z-50 bg-[#FAEEDA] border border-[#EF9F27] text-[#854F0B] px-6 py-3 flex items-center gap-3">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-[#BA7517]" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd" />
            </svg>
            <span class="text-sm font-medium">{{ warningMessage }}</span>
            <button @click="showWarning = false" class="text-[#BA7517] hover:text-[#854F0B]">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" /></svg>
            </button>
        </div>
    </transition>
  <div class="min-h-screen bg-[#F7F6F1] text-[#0F1115] font-sans">

    <header class="sticky top-0 z-50 border-b border-[#D8D5C9] bg-[#F7F6F1]/90 backdrop-blur">
      <div class="max-w-[1400px] mx-auto px-4 sm:px-6 py-4 flex items-center justify-between gap-3">
        <div class="flex items-center gap-3">
          <div class="w-9 h-9 flex items-center justify-center bg-[#0F1115] text-[#F7F6F1] font-mono text-[14px] font-medium">A</div>
          <div class="flex flex-col">
            <h1 class="text-[15px] font-medium tracking-[0.12em]" style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;">
              AMAS
            </h1>
            <span class="hidden sm:block text-[10px] text-[#888780] tracking-[0.14em] uppercase mt-0.5">
              Advanced Multi-Agent System
            </span>
          </div>
        </div>

        <!-- 会话信息 + 操作按钮（mission-control 风） -->
        <div class="flex items-center gap-3">
          <span class="hidden md:inline-flex px-3 py-1.5 border border-[#D8D5C9] rounded-full text-[11px] font-mono text-[#3B3D43]">
            {{ sessionId ? sessionId.substring(0, 14) + '...' : '...' }}
          </span>
          <span class="hidden sm:inline-flex px-3 py-1.5 border border-[#0F1115] rounded-full text-[11px] font-mono text-[#0F1115] items-center gap-2">
            <span class="w-1.5 h-1.5 rounded-full bg-[#0F6E56] animate-pulse"></span>
            OPERATIONAL
          </span>
          <button
            @click="handleNewSession"
            class="px-3 sm:px-4 py-1.5 bg-[#0F1115] text-[#F7F6F1] text-[11px] font-medium tracking-[0.1em] uppercase rounded hover:bg-[#3B3D43] transition-colors whitespace-nowrap"
          >
            + NEW<span class="hidden sm:inline"> SESSION</span>
          </button>
        </div>
      </div>
    </header>

    <main class="max-w-[1400px] mx-auto p-4 sm:p-6 lg:p-8 grid grid-cols-1 lg:grid-cols-12 gap-5">
      
      <aside class="lg:col-span-4 space-y-4">

        <!-- 知识库（Knowledge Base） -->
        <section class="bg-white border border-[#D8D5C9] p-5 space-y-4">
          <div class="flex justify-between items-center">
            <label class="text-[10px] font-medium text-[#888780] tracking-[0.18em] uppercase">Knowledge base</label>
            <span class="text-[10px] text-[#888780] border border-[#D8D5C9] px-2 py-0.5 font-mono">MAX 5 PDFs</span>
          </div>

          <div
              @dragover.prevent="isDragging = true"
              @dragleave.prevent="isDragging = false"
              @drop.prevent="handleDrop"
              class="relative group cursor-pointer border border-dashed border-[#888780] hover:border-[#0F1115] transition-colors p-5 text-center bg-[#F7F6F1]"
              :class="isDragging ? 'border-[#0F1115] bg-[#FFF]' : ''"
          >
            <input type="file" multiple accept=".pdf" class="absolute inset-0 opacity-0 cursor-pointer" @change="handleFileSelect" />

            <div v-if="uploadedFiles.length === 0" class="pointer-events-none flex flex-col items-center">
              <svg width="22" height="26" viewBox="0 0 24 28" fill="none" stroke="#888780" stroke-width="1.2">
                <path d="M5 1h9l5 5v21H5z"/><path d="M14 1v5h5"/>
              </svg>
              <p class="text-[12px] text-[#3B3D43] mt-2 font-medium">Drop PDFs here</p>
              <p class="text-[10px] text-[#888780] mt-1 font-mono">.pdf · 20 MB max</p>
            </div>

            <div v-else class="w-full space-y-2 pointer-events-none z-10">
              <div v-for="(file, i) in uploadedFiles" :key="i" class="flex items-center justify-between bg-white border border-[#E7E4D8] px-3 py-2 text-xs animate-fade-in-up">
                <div class="flex items-center gap-2 overflow-hidden">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#E24B4A" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><polyline points="14 2 14 8  20 8"/></svg>
                  <span class="truncate max-w-[150px] text-[#3B3D43] font-medium">{{ file.name }}</span>
                </div>
                <svg class="w-4 h-4 text-[#0F6E56]" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>
              </div>
            </div>
          </div>

          <!-- Doc Only / Hybrid 模式 -->
          <div class="grid grid-cols-2 border border-[#D8D5C9]">
            <button
                @click="setMode('document')"
                :disabled="uploadedFiles.length === 0"
                class="py-2.5 text-[10px] font-medium tracking-[0.1em] uppercase flex items-center justify-center gap-1.5 transition-colors"
                :class="[
                  searchMode === 'document' ? 'bg-[#0F1115] text-[#F7F6F1]' : 'text-[#888780] hover:text-[#3B3D43]',
                  uploadedFiles.length === 0 ? 'opacity-50 cursor-not-allowed' : ''
                ]"
            >
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18"/></svg>
              Doc Only
            </button>
            <button
                @click="setMode('hybrid')"
                class="py-2.5 text-[10px] font-medium tracking-[0.1em] uppercase flex items-center justify-center gap-1.5 transition-colors"
                :class="searchMode === 'hybrid' ? 'bg-[#0F1115] text-[#F7F6F1]' : 'text-[#888780] hover:text-[#3B3D43]'"
            >
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 2a14.5 14.5 0 0 1 0 20"/></svg>
              Hybrid
            </button>
          </div>
        </section>

        <!-- 已索引知识库 -->
        <section class="bg-white border border-[#D8D5C9] p-5 space-y-4">
          <div class="flex items-end justify-between gap-3">
            <div class="min-w-0 flex-1">
              <label for="knowledge-store" class="block text-[10px] font-medium text-[#888780] tracking-[0.18em] uppercase">
                Knowledge store
              </label>
              <select
                  id="knowledge-store"
                  v-model="activeKnowledgeBaseId"
                  @change="loadKnowledgeDocuments"
                  class="mt-2 w-full bg-white border border-[#D8D5C9] px-3 py-2 text-[12px] font-medium text-[#0F1115] focus:outline-none focus:border-[#0F1115]"
              >
                <option
                    v-for="kb in knowledgeBases"
                    :key="kb.knowledge_base_id"
                    :value="kb.knowledge_base_id"
                >
                  {{ kb.name }}
                </option>
              </select>
            </div>
            <button
                type="button"
                @click="refreshKnowledgePanel"
                class="h-[34px] w-[34px] shrink-0 border border-[#D8D5C9] text-[#888780] hover:border-[#0F1115] hover:text-[#0F1115] flex items-center justify-center transition-colors"
                title="Refresh knowledge base"
                aria-label="Refresh knowledge base"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 0 0-15.74-6L3 8"/><path d="M3 3v5h5"/><path d="M3 12a9 9 0 0 0 15.74 6L21 16"/><path d="M16 16h5v5"/></svg>
            </button>
          </div>

          <div class="grid grid-cols-2 gap-2">
            <div class="bg-[#F7F6F1] border border-[#E7E4D8] px-3 py-2.5">
              <div class="text-[10px] text-[#888780] font-medium uppercase tracking-[0.16em]">Bases</div>
              <div class="text-[22px] font-medium text-[#0F1115] font-mono mt-1.5">{{ knowledgeBases.length }}</div>
            </div>
            <div class="bg-[#F7F6F1] border border-[#E7E4D8] px-3 py-2.5">
              <div class="text-[10px] text-[#888780] font-medium uppercase tracking-[0.16em]">Documents</div>
              <div class="text-[22px] font-medium text-[#0F1115] font-mono mt-1.5">{{ knowledgeDocuments.length }}</div>
            </div>
          </div>

          <div v-if="knowledgeLoading" class="text-xs text-[#888780] py-2 font-mono">Loading knowledge base...</div>
          <div v-else-if="knowledgeDocuments.length === 0" class="text-xs text-[#888780] font-mono py-2">No indexed documents yet.</div>
          <div v-else class="space-y-1 max-h-28 overflow-y-auto">
            <div
                v-for="doc in knowledgeDocuments.slice(0, 4)"
                :key="doc.document_id"
                class="flex items-center justify-between bg-white border border-[#E7E4D8] px-3 py-2 text-xs"
            >
              <span class="truncate text-[#3B3D43]">{{ doc.original_filename || doc.filename }}</span>
              <span class="text-[10px] text-[#888780] shrink-0 font-mono">{{ doc.chunk_count || 0 }} chunks</span>
            </div>
          </div>
          <div v-if="knowledgeError" class="text-[11px] text-[#A32D2D] font-mono">{{ knowledgeError }}</div>
        </section>

        <!-- Human Checkpoint -->
        <section class="bg-white border border-[#D8D5C9] p-5 space-y-3">
          <div class="text-[10px] font-medium text-[#888780] uppercase tracking-[0.18em]">Human checkpoint</div>
          <select
              v-model="hitlPauseBefore"
              :disabled="isLoading"
              class="w-full bg-white border border-[#D8D5C9] px-3 py-2 text-[12px] font-medium text-[#0F1115] focus:outline-none focus:border-[#0F1115] disabled:opacity-50"
          >
            <option value="">No pause</option>
            <option value="planner">Before planning</option>
            <option value="researcher">Before research</option>
            <option value="writer">Before writing / revising</option>
            <option value="reviewer">Before review</option>
            <option value="refiner">Before refining only</option>
          </select>

          <p class="text-[10px] leading-relaxed text-[#888780]">
            “Before writing / revising” also pauses follow-up edits before the report is regenerated.
          </p>

          <textarea
              v-model="query"
              class="w-full px-3 py-3 bg-white border border-[#D8D5C9] text-[13px] text-[#0F1115] placeholder-[#888780] focus:outline-none focus:border-[#0F1115] resize-none leading-relaxed transition-colors"
              rows="3"
              placeholder="Enter research topic..."
              :disabled="isLoading"
          ></textarea>

          <button
              @click="startResearch"
              :disabled="isLoading || !query"
              class="w-full bg-[#0F1115] text-[#F7F6F1] py-3 text-[11px] font-medium tracking-[0.14em] uppercase hover:bg-[#3B3D43] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <span v-if="isLoading">Processing...</span>
            <span v-else>Initiate Research →</span>
          </button>

          <div v-if="hitlPause" class="mt-3 border border-[#BA7517] bg-[#FAEEDA] p-3">
            <p class="text-[11px] font-medium text-[#BA7517]">Paused before {{ hitlPause.pause_node }}</p>
            <p class="mt-1 text-[10px] text-[#854F0B]">{{ hitlPause.prompt }}</p>
            <textarea
                v-model="hitlInput"
                rows="3"
                class="mt-2 w-full resize-none border border-[#BA7517] bg-white p-2 text-xs text-[#0F1115] focus:outline-none focus:border-[#854F0B]"
                placeholder="Add instructions, constraints, or evidence requirements..."
            ></textarea>
            <button
                @click="resumeResearch"
                :disabled="isLoading"
                class="mt-2 w-full bg-[#BA7517] text-white py-2 text-[11px] font-medium uppercase tracking-[0.1em] hover:bg-[#854F0B] disabled:opacity-50 transition-colors"
            >
              Continue research
            </button>
          </div>
        </section>

      </aside>

      <!-- 右侧主区（核心：思维链顶部大尺寸 + 报告展示） -->
      <div class="lg:col-span-8 flex flex-col gap-5 min-h-[700px]">
        <!-- 工作流思维链（大尺寸横排，作为右侧主区核心展示） -->
        <WorkflowChain :currentStep="currentStep" />

        <!-- Researcher 内部 Agentic RAG 子流程 -->
        <ResearchProcess
            :events="researchEvents"
            :active="isLoading && currentStep === 'researcher'"
        />

        <!-- 实时执行流：前端动作 + 后端 SSE 工作流事件 -->
        <section class="border border-[#0F1115] overflow-hidden shadow-[4px_4px_0_#D8D5C9]" aria-label="Execution stream">
          <div class="flex items-center justify-between gap-4 px-4 py-3 bg-[#0F1115] border-b border-[#3B3D43]">
            <div class="flex items-center gap-3 min-w-0">
              <div class="hidden sm:flex items-center gap-1.5 shrink-0" aria-hidden="true">
                <span class="w-2 h-2 rounded-full bg-[#E24B4A]"></span>
                <span class="w-2 h-2 rounded-full bg-[#EF9F27]"></span>
                <span class="w-2 h-2 rounded-full bg-[#1D9E75]"></span>
              </div>
              <div class="min-w-0">
                <h2 class="text-[11px] font-medium tracking-[0.18em] text-white uppercase">Execution stream</h2>
                <p class="hidden sm:block mt-1 text-[10px] font-mono text-[#888780] truncate">FRONTEND ACTIONS · BACKEND WORKFLOW EVENTS</p>
              </div>
            </div>
            <div class="flex items-center gap-3 shrink-0 font-mono text-[10px]">
              <span class="text-[#888780]">{{ logs.length }} EVENTS</span>
              <span
                  class="inline-flex items-center gap-1.5 border px-2 py-1 tracking-[0.12em]"
                  :class="isLoading ? 'border-[#5DCAA5] text-[#5DCAA5]' : 'border-[#5F5E5A] text-[#B4B2A9]'"
              >
                <span class="w-1.5 h-1.5 rounded-full" :class="isLoading ? 'bg-[#5DCAA5] animate-pulse' : 'bg-[#5F5E5A]'"></span>
                {{ isLoading ? 'LIVE' : 'READY' }}
              </span>
            </div>
          </div>
          <div
              ref="logsContainer"
              class="h-40 sm:h-44 p-4 overflow-y-auto bg-[#0F1115] font-mono text-[11px] sm:text-[12px] leading-6 space-y-0.5 scrollbar-thin"
              role="log"
              aria-live="polite"
          >
            <div v-if="logs.length === 0" class="flex items-center gap-2 text-[#5F5E5A] italic">
              <span class="text-[#5DCAA5]">›</span>
              System ready. Waiting for input...
            </div>
            <div v-for="(log, i) in logs" :key="i" class="flex gap-3 border-l border-[#26282E] pl-3">
              <span class="text-[#5DCAA5] shrink-0 select-none">{{ String(i + 1).padStart(2, '0') }}</span>
              <span class="break-all" :class="logTone(log)">{{ log }}</span>
            </div>
            <div v-if="isLoading" class="flex items-center gap-2 text-[#5DCAA5] mt-1">
              <span class="animate-pulse">●</span>
              <span class="animate-pulse">Listening for workflow events...</span>
            </div>
          </div>
        </section>

        <!-- 报告展示区（thinking / markdown 渲染） -->
        <div class="flex-1 bg-white border border-[#D8D5C9] p-8 lg:p-10 min-h-[460px] flex flex-col">
          <div v-if="!displayedReport && !isLoading" class="flex-1 flex flex-col items-center justify-center text-[#888780] space-y-4">
            <svg width="46" height="54" viewBox="0 0 24 28" fill="none" stroke="currentColor" stroke-width="1.2" class="text-[#B4B2A9]">
              <path d="M5 1h9l5 5v21H5z"/><path d="M14 1v5h5"/>
            </svg>
            <div class="text-center">
              <h3 class="text-[15px] font-medium text-[#0F1115]">Awaiting Assignment</h3>
              <p class="text-[12px] mt-1">Enter a research topic to begin.</p>
            </div>
          </div>

          <div v-else-if="isLoading && !displayedReport" class="flex-1 flex flex-col items-center justify-center relative">
            <div class="relative w-24 h-24 flex items-center justify-center">
              <div class="absolute inset-0 border border-[#0F1115] animate-ping opacity-40"></div>
              <div class="absolute inset-3 border border-[#0F1115] animate-pulse opacity-60"></div>
              <div class="w-3 h-3 bg-[#0F1115]"></div>
            </div>
            <div class="mt-8 text-center">
              <h3 class="text-[13px] font-medium tracking-[0.2em] uppercase text-[#0F1115] animate-pulse">Thinking</h3>
              <p class="text-[11px] text-[#888780] font-mono mt-1">ANALYZE &amp; PLAN STRATEGY...</p>
            </div>
          </div>

          <div v-else class="prose prose-slate max-w-none prose-headings:font-display prose-headings:font-bold prose-headings:tracking-tight prose-a:text-blue-600 prose-img:rounded-xl">
            <div v-html="renderedReport"></div>
            <span v-if="isTyping" class="inline-block w-2 h-4 bg-[#0F1115] ml-1 animate-pulse align-middle"></span>
          </div>
        </div>
      </div>

    </main>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted } from 'vue';
import { uploadFiles, streamChat, resumeChat, clearContext, getOrCreateSessionId, getCurrentSessionId, clearSession, getSessionInfo, listKnowledgeBases, listKnowledgeBaseDocuments } from './services/api';
import WorkflowChain from './components/WorkflowChain.vue';
import ResearchProcess from './components/ResearchProcess.vue';
import MarkdownIt from 'markdown-it';
// 【修复步骤 1】引入数学公式插件 (必须先 npm install markdown-it-katex)
import mk from 'markdown-it-katex';

// 【修复步骤 2】挂载插件
const md = new MarkdownIt({
    html: true,
    linkify: true,
    typographer: true
});
md.use(mk);
const showWarning = ref(false);
const warningMessage = ref('');
const triggerWarning = (msg) => {
    warningMessage.value = msg;
    showWarning.value = true;
    // 5秒后自动消失
    setTimeout(() => {
        showWarning.value = false;
    }, 5000);
};


// 状态变量
const query = ref('');
const isLoading = ref(false);
const currentStep = ref('idle'); 
const logs = ref([]);
const logsContainer = ref(null);
const uploadedFiles = ref([]); 
const isDragging = ref(false);
const searchMode = ref('hybrid'); 
const knowledgeBases = ref([]);
const knowledgeDocuments = ref([]);
const activeKnowledgeBase = ref(null);
const activeKnowledgeBaseId = ref('kb_default');
const knowledgeLoading = ref(false);
const knowledgeError = ref('');
const hitlPauseBefore = ref('');
const hitlPause = ref(null);
const hitlInput = ref('');
const researchEvents = ref([]);

// 打字机变量
const displayedReport = ref('');
const isTyping = ref(false);

// ─── 会话管理（Phase 2 新增）───
const sessionId = ref(null);
const sessionTurnCount = ref(0);
const sessionHistory = ref(null);  // { episodic, semantic, window_k, ... }
const showHistory = ref(false);

async function initializeApp() {
  sessionId.value = await getOrCreateSessionId();
  logs.value.push(`[SESSION] Loaded session: ${sessionId.value}`);
  await loadSessionHistory();
  await refreshKnowledgePanel();
}

// 页面加载时初始化会话
onMounted(initializeApp);

async function refreshKnowledgePanel() {
    knowledgeLoading.value = true;
    knowledgeError.value = '';
    try {
        const bases = await listKnowledgeBases();
        knowledgeBases.value = bases.items || [];
        if (!knowledgeBases.value.some(kb => kb.knowledge_base_id === activeKnowledgeBaseId.value)) {
            activeKnowledgeBaseId.value = knowledgeBases.value.find(kb => kb.knowledge_base_id === 'kb_default')?.knowledge_base_id || knowledgeBases.value[0]?.knowledge_base_id || '';
        }
        activeKnowledgeBase.value = knowledgeBases.value.find(kb => kb.knowledge_base_id === activeKnowledgeBaseId.value) || null;

        await loadKnowledgeDocuments();
    } catch (e) {
        knowledgeError.value = e.message || 'Failed to load knowledge base';
    } finally {
        knowledgeLoading.value = false;
    }
}

async function loadKnowledgeDocuments() {
    activeKnowledgeBase.value = knowledgeBases.value.find(kb => kb.knowledge_base_id === activeKnowledgeBaseId.value) || null;
    if (!activeKnowledgeBase.value) {
        knowledgeDocuments.value = [];
        return;
    }
    const docs = await listKnowledgeBaseDocuments(activeKnowledgeBase.value.knowledge_base_id);
    knowledgeDocuments.value = docs.items || [];
}

async function loadSessionHistory() {
  if (!sessionId.value) return;
  try {
    const info = await getSessionInfo(sessionId.value);
    sessionTurnCount.value = info.turns_count || 0;
    logs.value.push(`[SESSION] Turns: ${sessionTurnCount.value}, Budget: ${(info.total_actual_tokens || 0).toLocaleString()} tokens`);
  } catch (e) {
    console.warn('Failed to load session info:', e);
  }
}

async function handleNewSession() {
  await clearSession();
  sessionId.value = await getOrCreateSessionId();
  sessionTurnCount.value = 0;
  sessionHistory.value = null;
  displayedReport.value = '';
  researchEvents.value = [];
  logs.value = [];
  logs.value.push(`[SESSION] New session: ${sessionId.value}`);
}

function handleSessionEvent(data) {
  if (data.session_id && data.session_id !== sessionId.value) {
    sessionId.value = data.session_id;
  }
  sessionTurnCount.value = data.turn_number || sessionTurnCount.value;
  if (data.window_stats) {
    logs.value.push(`[SESSION] Turn #${data.turn_number} | Window K=${data.window_stats.window_k} | ` +
      `Episodic: ${data.window_stats.episodic_count}, Semantic: ${data.window_stats.semantic_count}`);
  }
}

function handleResearchProgress(event) {
  const previousPass = researchEvents.value.at(-1)?.pass || 0;
  const pass = event.stage === 'initialize' && event.status === 'running'
    ? previousPass + 1
    : Math.max(1, previousPass);
  const normalizedEvent = { ...event, pass };

  researchEvents.value = [...researchEvents.value, normalizedEvent].slice(-100);
  currentStep.value = 'researcher';

  const round = normalizedEvent.iteration || 1;
  const label = normalizedEvent.label || normalizedEvent.stage || 'Research';
  const details = normalizedEvent.details || {};
  let metric = '';
  if (Number.isFinite(Number(details.candidate_count))) metric = ` · ${details.candidate_count} candidates`;
  else if (Number.isFinite(Number(details.evidence_count))) metric = ` · ${details.evidence_count} evidence`;
  else if (Number.isFinite(Number(details.query_count))) metric = ` · ${details.query_count} queries`;
  else if (typeof details.sufficient === 'boolean') metric = details.sufficient ? ' · sufficient' : ' · gap found';

  if (normalizedEvent.status === 'running') {
    logs.value.push(`[RAG P${pass}/R${round}] → ${label}: ${normalizedEvent.message || 'Running'}${metric}`);
  } else if (normalizedEvent.status === 'completed') {
    logs.value.push(`[RAG P${pass}/R${round}] ✓ ${label}${metric} · ${normalizedEvent.duration_ms || 0}ms`);
  } else if (normalizedEvent.status === 'failed') {
    logs.value.push(`[RAG P${pass}/R${round}] ! ${label} failed: ${normalizedEvent.error || 'Unknown error'}`);
  }
}

// 【修复步骤 3】增强渲染逻辑：把后端返回的 \[...\] 替换成插件能识别的 $$...$$
const renderedReport = computed(() => {
    let raw = displayedReport.value || '';
    
    // 1. 预处理：修复 LaTeX 定界符
    // 将 \[ ... \] 替换为 $$ ... $$ (块级公式)
    raw = raw.replace(/\\\[/g, '$$$').replace(/\\\]/g, '$$$');
    
    // 将 \( ... \) 替换为 $ ... $ (行内公式)
    raw = raw.replace(/\\\(/g, '$').replace(/\\\)/g, '$');

    // 2. 额外补丁：有些模型会输出不带反斜杠的 [ formula ]，这比较少见但要防备
    // 注意：这里需要小心不要误伤 Markdown 链接 [text](url)
    // 简单的策略是：如果 [ 后面跟着 \text 或 \frac 等 LaTeX 关键字，就认为是公式
    raw = raw.replace(/\[\s*(\\text|\\frac|\\sum|\\int)/g, '$$$$ $1'); 
    // 对应的闭合 ] 很难精准匹配，通常标准的 \[ \] 替换就够了。
    
    // 3. 渲染
    return md.render(raw);
});

// 执行流按事件类型着色，便于快速定位警告、错误和完成节点。
const logTone = (log) => {
    if (log.startsWith('[ERROR]') || log.includes('FAILED') || log.includes('terminated')) return 'text-[#F09595]';
    if (log.startsWith('[HITL]') || log.startsWith('[QA]')) return 'text-[#FAC775]';
    if (log.startsWith('[RAG')) return 'text-[#5DCAA5]';
    if (log.startsWith('[DONE]')) return 'text-[#5DCAA5]';
    if (log.startsWith('[PLANNER]') || log.startsWith('[RESEARCHER]') || log.startsWith('[WRITER]') || log.startsWith('[REFINER]')) return 'text-[#85B7EB]';
    return 'text-[#E7E4D8]';
};

const scrollToBottom = async () => {
    await nextTick();
    if (logsContainer.value) logsContainer.value.scrollTop = logsContainer.value.scrollHeight;
};

// --- 文件处理逻辑 ---
const handleFileSelect = async (event) => {
    processFiles(event.target.files);
};

const handleDrop = async (event) => {
    isDragging.value = false;
    processFiles(event.dataTransfer.files);
};

const processFiles = async (files) => {
    if (files.length > 5) {
        alert("Maximum 5 files allowed!");
        return;
    }
    
    uploadedFiles.value = Array.from(files);
    
    if (uploadedFiles.value.length > 0) {
        logs.value.push(`[SYSTEM] Uploading ${files.length} document(s)...`);
        try {
            const res = await uploadFiles(uploadedFiles.value, activeKnowledgeBaseId.value);
            logs.value.push(`[SYSTEM] Knowledge base built. ${res.chunks_stored} chunks indexed.`);
            activeKnowledgeBaseId.value = res.knowledge_base_id || activeKnowledgeBaseId.value;
            await refreshKnowledgePanel();
        } catch (e) {
            logs.value.push(`[ERROR] Upload failed: ${e.message}`);
            alert("Upload failed: " + e.message);
            uploadedFiles.value = []; 
        }
    }
};

const setMode = (mode) => {
    searchMode.value = mode;
};

let typingInterval = null;
const typeWriterEffect = (text) => {
    isTyping.value = true;
    
    // 【关键修复】：如果当前有正在运行的打字机，立刻干掉它！防止文字重叠并发
    if (typingInterval) {
        clearInterval(typingInterval);
    }
    
    let index = 0;
    typingInterval = setInterval(() => {
        if (index < text.length) {
            displayedReport.value += text.slice(index, index + 3);
            index += 3;
        } else {
            clearInterval(typingInterval);
            typingInterval = null; // 清空记录
            isTyping.value = false;
        }
    }, 10);
};

// --- 开始研究 ---
const startResearch = async () => { 
    if (!query.value) return;
    
    isLoading.value = true;
    currentStep.value = 'planner'; 
    logs.value = []; 
    logs.value.push(`[INIT] System initialized. Mode: ${searchMode.value.toUpperCase()}`);
    displayedReport.value = '';
    researchEvents.value = [];
    hitlPause.value = null;
    hitlInput.value = '';
    
    const actualMode = uploadedFiles.value.length === 0 ? 'hybrid' : searchMode.value;

    try {
        if (uploadedFiles.value.length > 0) {
            logs.value.push(`[SYSTEM] Uploading ${uploadedFiles.value.length} document(s)...`);
            const res = await uploadFiles(uploadedFiles.value, activeKnowledgeBaseId.value);
            logs.value.push(`[SYSTEM] Knowledge base built. ${res.chunks_stored} chunks indexed.`);
            activeKnowledgeBaseId.value = res.knowledge_base_id || activeKnowledgeBaseId.value;
            await refreshKnowledgePanel();
        } else {
            logs.value.push(`[SYSTEM] Clearing previous knowledge base...`);
            await clearContext(activeKnowledgeBaseId.value);
            await refreshKnowledgePanel();
            logs.value.push(`[SYSTEM] Context cleared. Running in pure Web Search mode.`);
        }

        streamChat(
            query.value,
            actualMode,
            (data) => {
                    if (data.step === '__research_progress__') {
                        handleResearchProgress(data.data);
                        scrollToBottom();
                        return;
                    }

                    if (data.step === '__hitl_pause__') {
                        hitlPause.value = data.data;
                        currentStep.value = 'paused';
                        isLoading.value = false;
                        logs.value.push(`[HITL] Paused before ${data.data.pause_node}. Waiting for input.`);
                        scrollToBottom();
                        return;
                    }

                    // Phase 2: 处理会话事件
                    if (data.step === '__session__') {
                        handleSessionEvent(data.data);
                        return;
                    }

                    // 1. 同步后端当前步骤
                    if (data.step) currentStep.value = data.step;

                    // --- 步骤 1: 规划 (Planner) ---
                    if (data.step === 'planner') {
                        currentStep.value = 'researcher'; // 视觉上跳到下一步
                        logs.value.push(`[PLANNER] Strategy: [${data.data.plan.join(', ')}]`);
                    }

                    // --- 步骤 2: 搜索 (Researcher) ---
                    else if (data.step === 'researcher') {
                        const results = data.data.search_results || [];
                        const resultsStr = JSON.stringify(results);

                        // [核心修改] 检测严重警告（熔断停止）
                        if (resultsStr.includes("流程已终止")) {
                            triggerWarning("⛔️ 文档与问题无关，任务已强制停止");
                            logs.value.push(`[SYSTEM] Task terminated: Context irrelevant in Doc-Only mode.`);
                            currentStep.value = 'done'; // 强制结束状态
                            return; // 关键：直接返回，不再执行下面的代码，防止跳到 writer
                        }

                        // 检测普通警告（自动切换等）
                        if (resultsStr.includes("自动切换为全网搜索")) {
                            triggerWarning("⚠️ 文档与问题无关，已自动切换为全网搜索");
                        } else if (resultsStr.includes("Document Only 模式")) {
                            triggerWarning("⚠️ 文档与问题无关，无法回答");
                        }

                        // 如果没有停止，则正常流转到 writer
                        currentStep.value = 'writer';
                        logs.value.push(`[RESEARCHER] Data acquisition complete. Items: ${results.length}`);
                    }

                    // --- 步骤 3: 写作 (Writer) ---
                    else if (data.step === 'writer') {
                        currentStep.value = 'reviewer';
                        logs.value.push(`[WRITER] Drafting content...`);
                        if (data.data.final_report) {
                            displayedReport.value = '';
                            typeWriterEffect(data.data.final_report);
                        }
                    }

                    // --- 步骤 4: 审查 (Reviewer) ---
                    else if (data.step === 'reviewer') {
                        if (data.data.review_status === 'FAIL') {
                            logs.value.push(`[QA] Review FAILED: ${data.data.critique} -> Rerolling`);
                            currentStep.value = 'planner';
                        } else {
                            logs.value.push(`[QA] Review PASSED.`);
                        }
                    }
                    else if (data.step === 'refiner') {
                    currentStep.value = 'writer'; // UI上复用写作状态
                    logs.value.push(`[REFINER] Modifying report based on feedback...`);
                    if (data.data.final_report) {
                        displayedReport.value = '';
                        // 重新打字输出修改后的报告
                        typeWriterEffect(data.data.final_report);
                    }
                }

                    scrollToBottom();
                },
            () => {
                isLoading.value = false;
                currentStep.value = 'done';
                logs.value.push('[DONE] Process complete.');
                // 刷新会话历史（异步，不阻塞）
                loadSessionHistory();
                scrollToBottom();
            },
            (err) => {
                isLoading.value = false;
                logs.value.push(`[ERROR] ${err.message}`);
                scrollToBottom();
            },
            (sessionData) => {
                // onSession callback
                handleSessionEvent(sessionData);
            },
            sessionId.value,  // 传入当前会话 ID
            activeKnowledgeBaseId.value,
            hitlPauseBefore.value,
        );
    } catch (e) {
        isLoading.value = false;
        logs.value.push(`[ERROR] Initialization failed: ${e.message}`);
        alert("System Error: " + e.message);
    }
};

const resumeResearch = async () => {
    if (!hitlPause.value?.thread_id) return;
    isLoading.value = true;
    currentStep.value = hitlPause.value.pause_node || 'planner';
    logs.value.push(`[HITL] Resuming ${currentStep.value} with human input.`);

    resumeChat(
        hitlPause.value.thread_id,
        hitlInput.value,
        (data) => {
            if (data.step === '__research_progress__') {
                handleResearchProgress(data.data);
                scrollToBottom();
                return;
            }

            if (data.step === '__hitl_pause__') {
                hitlPause.value = data.data;
                isLoading.value = false;
                currentStep.value = 'paused';
                return;
            }
            if (data.step) currentStep.value = data.step;
            if (data.step === 'planner') {
                logs.value.push(`[PLANNER] Strategy: [${data.data.plan.join(', ')}]`);
            } else if (data.step === 'researcher') {
                logs.value.push(`[RESEARCHER] Data acquisition complete. Items: ${(data.data.search_results || []).length}`);
            } else if (data.step === 'writer' || data.step === 'refiner') {
                if (data.data.final_report) {
                    displayedReport.value = '';
                    typeWriterEffect(data.data.final_report);
                }
            } else if (data.step === 'reviewer') {
                logs.value.push(`[QA] Review ${data.data.review_status || 'completed'}.`);
            }
            scrollToBottom();
        },
        () => {
            isLoading.value = false;
            currentStep.value = 'done';
            hitlPause.value = null;
            hitlInput.value = '';
            logs.value.push('[DONE] Process complete.');
            loadSessionHistory();
            scrollToBottom();
        },
        (err) => {
            isLoading.value = false;
            logs.value.push(`[ERROR] ${err.message}`);
            scrollToBottom();
        },
        handleSessionEvent,
    );
};
</script>

<style>
@import 'https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css';

/* 保持原有的动画样式 */
.slide-down-enter-active,
.slide-down-leave-active {
  transition: all 0.3s ease;
}
.slide-down-enter-from,
.slide-down-leave-to {
  transform: translate(-50%, -100%);
  opacity: 0;
}
@keyframes blob {
    0% { transform: translate(0px, 0px) scale(1); }
    33% { transform: translate(30px, -50px) scale(1.1); }
    66% { transform: translate(-20px, 20px) scale(0.9); }
    100% { transform: translate(0px, 0px) scale(1); }
}
.animate-blob {
    animation: blob 7s infinite;
}
.animation-delay-2000 { animation-delay: 2s; }
.animation-delay-4000 { animation-delay: 4s; }

/* 简单的淡入动画 */
@keyframes fadeInUp {
    from { opacity: 0; transform: translateY(5px); }
    to { opacity: 1; transform: translateY(0); }
}
.animate-fade-in-up {
    animation: fadeInUp 0.3s ease-out;
}

/* 2. 关键修复：解决 Tailwind 与 KaTeX 的样式冲突 */
/* Tailwind 默认将所有元素设为 border-box，这会破坏 KaTeX 的布局算法 */
.katex * {
    box-sizing: content-box !important;
}

/* 3. 公式滚动条优化 */
.katex-display {
    overflow-x: auto;
    overflow-y: hidden;
    padding: 0.5em 0;
    margin: 1em 0 !important; /* 修正外边距 */
}

/* --- 全局字体优化 --- */
body {
  font-family: theme('fontFamily.sans');
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* --- 舒适阅读风格 --- */
.prose {
  font-size: 1.05rem;
  color: #374151;
  line-height: 1.75;
}

/* 标题 */
.prose h1 {
  @apply text-3xl font-bold text-gray-900 mb-8 pb-4 border-b border-gray-100;
  font-family: theme('fontFamily.sans');
  line-height: 1.3;
}

.prose h2 {
  @apply text-xl font-bold text-gray-800 mt-10 mb-4 flex items-center;
  font-family: theme('fontFamily.sans');
  position: relative;
  padding-left: 1rem;
}
.prose h2::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 4px;
  height: 1em;
  @apply bg-blue-600 rounded-full;
}

.prose h3 {
  @apply text-lg font-bold text-gray-800 mt-8 mb-3;
  font-family: theme('fontFamily.sans');
}

/* 正文 */
.prose p {
  @apply text-justify mb-5 leading-relaxed text-gray-700;
}

/* 重点文字 */
.prose strong {
  @apply font-bold text-gray-900;
}

/* 摘要/引用块 */
.prose blockquote {
  font-style: normal !important;
  @apply my-8 pl-6 pr-4 py-5;
  @apply bg-gray-50 rounded-r-lg border-l-4 border-blue-500;
  @apply text-gray-700 text-base leading-relaxed; 
}

/* 列表 */
.prose ul {
  @apply list-disc list-outside ml-6 space-y-2 mb-6 text-gray-700;
}
.prose ol {
  @apply list-decimal list-outside ml-6 space-y-2 mb-6 text-gray-700;
}

/* 表格 */
.prose table {
  @apply w-full text-left border-collapse my-8 rounded-lg overflow-hidden border border-gray-200;
}
.prose thead {
  @apply bg-gray-50;
}
.prose th {
  @apply px-4 py-3 font-semibold text-gray-900 text-sm uppercase tracking-wide border-b border-gray-200;
}
.prose td {
  @apply px-4 py-3 text-sm text-gray-600 border-b border-gray-100;
}
.prose tr:hover td {
  @apply bg-blue-50/30 transition-colors;
}

/* 代码块 */
.prose pre {
  @apply bg-[#1e293b] text-gray-100 rounded-xl p-5 my-6 overflow-x-auto shadow-lg;
  font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
  font-size: 0.9em;
}
.prose code {
  @apply text-blue-600 bg-blue-50 px-1.5 py-0.5 rounded text-sm font-medium mx-0.5;
  font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
}
.prose pre code {
  @apply bg-transparent text-gray-100 p-0 text-xs;
}

/* KaTeX 字体微调 */
.katex {
  font-size: 1.15em;
  font-family: 'Times New Roman', serif;
}
</style>
