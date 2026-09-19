<template>
  <!--
    检索计划卡片（S10）

    视觉语言**完全复用 ResearchProcess.vue**：白底 + #D8D5C9 边框 + #0F6E56 主绿、
    11px/10px/9px 的字号阶梯、方角（无 rounded）。
    刻意不引入参考项目 ai-picture-editor 的 Tailwind 自定义 token ——
    那套 token 和本研究系统既有的米色/墨绿配色会打架（全局风险：样式冲突）。

    这张卡片要回答用户的三个问题：
      ① 准备跑哪几条检索？        → 任务列表（tool + query + note）
      ② 现在跑到哪了？            → 每行的状态徽标 + 进度条 + 耗时
      ③ 哪条失败了？              → FAILED 行的错误信息 + 重试按钮
  -->
  <section class="border border-[#D8D5C9] bg-white" aria-label="Search plan">
    <header class="flex flex-col gap-3 border-b border-[#E7E4D8] px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
      <div class="flex items-center gap-3">
        <div class="flex h-9 w-9 items-center justify-center bg-[#0F6E56] font-mono text-[11px] font-medium text-white">
          DAG
        </div>
        <div>
          <div class="flex items-center gap-2">
            <h2 class="text-[11px] font-medium uppercase tracking-[0.18em] text-[#0F1115]">Search plan</h2>
            <span class="border border-[#9FE1CB] bg-[#E1F7EF] px-1.5 py-0.5 text-[9px] font-medium tracking-[0.12em] text-[#0F6E56]">
              TASK DAG
            </span>
          </div>
          <p class="mt-1 text-[10px] text-[#888780]">FAN-OUT · FAILURE ISOLATION · SELECTABLE</p>
        </div>
      </div>

      <div class="flex items-center gap-2 font-mono text-[9px] sm:justify-end">
        <span class="border border-[#D8D5C9] px-2 py-1 text-[#5F5E5A]">ROUND {{ iteration }}</span>
        <span class="border border-[#D8D5C9] px-2 py-1 text-[#5F5E5A]">{{ tasks.length }} TASKS</span>
        <span class="border border-[#D8D5C9] px-2 py-1 text-[#5F5E5A]">{{ doneCount }} DONE</span>
        <span class="inline-flex items-center gap-1.5 border px-2 py-1 tracking-[0.12em]" :class="overallClass">
          <span class="h-1.5 w-1.5 rounded-full" :class="overallDotClass"></span>
          {{ overallLabel }}
        </span>
      </div>
    </header>

    <!-- 计划拆解理由：模型为什么这样拆，让人能一眼判断它有没有乱拆 -->
    <p v-if="rationale" class="border-b border-[#E7E4D8] bg-[#F7F6F1] px-4 py-2 text-[10px] text-[#3B3D43]">
      {{ rationale }}
    </p>

    <!-- 任务清单：一行一个子任务 -->
    <ul class="divide-y divide-[#E7E4D8]">
      <li
        v-for="task in tasks"
        :key="task.id"
        class="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
      >
        <div class="flex min-w-0 items-start gap-3">
          <!-- 多任务时才显示勾选框（单任务不打扰用户，与后端 needs_confirm 的阈值一致） -->
          <input
            v-if="selectable"
            type="checkbox"
            class="mt-0.5 h-3.5 w-3.5 shrink-0 accent-[#0F6E56]"
            :checked="task.status !== STATE.CANCELED"
            :disabled="isLocked(task)"
            @change="$emit('toggle-task', task.id)"
          />

          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <span class="font-mono text-[10px] font-medium text-[#0F1115]">{{ task.id }}</span>
              <!-- channel 徽标：这条主要覆盖哪条召回通道 -->
              <span
                v-if="task.channel"
                class="border border-[#D8D5C9] px-1.5 py-0.5 font-mono text-[9px] text-[#5F5E5A]"
              >
                {{ task.channel.toUpperCase() }}
              </span>
              <!-- 工具名：让人知道这条是查本地知识库还是查网络 -->
              <span class="text-[10px]" :class="task.tool === 'web.retrieve_candidates' ? 'text-[#888780]' : 'text-[#0F6E56]'">
                {{ toolLabel(task.tool) }}
              </span>
            </div>

            <p class="mt-1 truncate text-[11px] text-[#0F1115]">{{ task.params?.query || '—' }}</p>
            <!-- note 是这条任务负责覆盖哪块证据缺口 -->
            <p v-if="task.note" class="mt-0.5 truncate text-[10px] text-[#888780]">{{ task.note }}</p>
            <!-- 失败时把错误摊开，而不是只显示一个红点 -->
            <p v-if="task.error" class="mt-1 text-[10px] text-[#C0392B]">{{ task.error }}</p>
          </div>
        </div>

        <div class="flex shrink-0 items-center gap-2 font-mono text-[9px]">
          <!-- 单步进度条：走到 30% 就画 30%，不再让用户干等"研究中" -->
          <div v-if="task.status === STATE.RUNNING" class="h-1 w-16 bg-[#E7E4D8]">
            <div
              class="h-full bg-[#0F6E56] transition-all duration-300"
              :style="{ width: `${progressOf(task.id)}%` }"
            ></div>
          </div>
          <span v-if="task.duration_ms !== undefined" class="text-[#888780]">{{ task.duration_ms }} MS</span>
          <span class="border px-2 py-1 tracking-[0.12em]" :class="statusClass(task.status)">
            {{ statusLabel(task.status) }}
          </span>
        </div>
      </li>
    </ul>

    <!-- 操作区：照参考项目 AgentConversation.tsx 的三动作按状态显示 -->
    <footer v-if="selectable || hasFailure" class="flex items-center justify-end gap-2 border-t border-[#E7E4D8] px-4 py-2">
      <button
        v-if="canCancelRemaining"
        type="button"
        class="border border-[#D8D5C9] px-2 py-1 text-[10px] text-[#5F5E5A] hover:bg-[#F7F6F1]"
        @click="$emit('cancel-remaining')"
      >
        取消后续
      </button>
      <button
        v-if="hasFailure"
        type="button"
        class="border border-[#D8D5C9] px-2 py-1 text-[10px] text-[#5F5E5A] hover:bg-[#F7F6F1]"
        @click="$emit('retry-failed')"
      >
        重试失败项
      </button>
      <button
        v-if="awaitingConfirm"
        type="button"
        class="border border-[#0F6E56] bg-[#0F6E56] px-2 py-1 text-[10px] text-white hover:opacity-90"
        @click="$emit('confirm-plan', approvedIds)"
      >
        执行选中的 {{ approvedIds.length }} 条
      </button>
    </footer>
  </section>
</template>

<script setup>
/**
 * SearchPlanCard —— 检索计划卡片（S10）
 *
 * 【两种打开方式，同一个组件】
 *   1. 确认态（awaitingConfirm = true）：
 *      后端在 plan_review 节点 interrupt() 挂起，前端弹卡片让人勾选。
 *      此时按钮是"执行选中的 N 条"，点完调 /api/chat/resume 并把 approved_ids 带回去。
 *   2. 观测态（awaitingConfirm = false）：
 *      检索执行中，卡片只做展示 —— 每行显示独立状态、进度、耗时。
 *
 * 【★ 全局风险 R10：为什么必须做轮询兜底】
 *   第一步的 SSE 结束时，下一步可能还没把状态落库；
 *   只靠事件驱动的话，卡片会停在"等待中"不动（用户以为卡死了）。
 *   参考项目 useAgent.ts:24-26 用 800ms 轮询兜底，这里照搬这个间隔。
 *   见文件末尾的 startPolling / 待接线清单。
 *
 * 【状态文案的唯一来源】
 *   STEP_LABEL 的 7 个 key 与后端 app/graph/planner/dag.py 的 7 个状态常量**一一对应**。
 *   改后端状态机时这里必须同步改，否则会出现"后端说 canceled、前端显示未知"。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'

/* ------------------------------------------------------------------ */
/* 状态常量与文案映射                                                   */
/* ------------------------------------------------------------------ */

/** 与 app/graph/planner/dag.py 的 7 个状态常量严格对应 */
const STATE = {
  PENDING: 'pending',
  WAITING: 'waiting',
  QUEUED: 'queued',
  RUNNING: 'running',
  SUCCEEDED: 'succeeded',
  FAILED: 'failed',
  CANCELED: 'canceled',
}

/** 七态 → 中文文案 */
const STEP_LABEL = {
  [STATE.PENDING]: '待执行',
  [STATE.WAITING]: '待确认',
  [STATE.QUEUED]: '等待确认',
  [STATE.RUNNING]: '执行中',
  [STATE.SUCCEEDED]: '已完成',
  [STATE.FAILED]: '失败',
  [STATE.CANCELED]: '已取消',
}

/** 七态 → 徽标样式（沿用 ResearchProcess.vue 的配色：绿=正常、红=失败、灰=中性） */
const STEP_CLASS = {
  [STATE.PENDING]: 'border-[#D8D5C9] text-[#5F5E5A]',
  [STATE.WAITING]: 'border-[#D8D5C9] text-[#5F5E5A]',
  [STATE.QUEUED]: 'border-[#D8D5C9] text-[#5F5E5A]',
  [STATE.RUNNING]: 'border-[#9FE1CB] bg-[#E1F7EF] text-[#0F6E56]',
  [STATE.SUCCEEDED]: 'border-[#9FE1CB] bg-[#E1F7EF] text-[#0F6E56]',
  [STATE.FAILED]: 'border-[#F5C6C0] bg-[#FDEDEB] text-[#C0392B]',
  [STATE.CANCELED]: 'border-[#D8D5C9] bg-[#F7F6F1] text-[#888780]',
}

/* ------------------------------------------------------------------ */
/* props / emits                                                       */
/* ------------------------------------------------------------------ */

const props = defineProps({
  /** 检索计划：[{ id, tool, params: {query}, channel, note, status, error?, duration_ms? }] */
  tasks: { type: Array, default: () => [] },
  /** 模型给的拆解理由，展示在卡片顶部 */
  rationale: { type: String, default: '' },
  /** 当前检索轮次；一个 iteration 一组卡片 */
  iteration: { type: Number, default: 1 },
  /** true = 这份计划正在等用户勾选（对应后端的 search_plan_review 中断） */
  awaitingConfirm: { type: Boolean, default: false },
})

const emit = defineEmits([
  'toggle-task',      // 勾选/取消某条任务
  'confirm-plan',     // 确认执行选中的任务，携带 approved_ids
  'cancel-remaining', // 取消后续未开始的任务
  'retry-failed',     // 重试失败项
])

/* ------------------------------------------------------------------ */
/* 派生状态                                                            */
/* ------------------------------------------------------------------ */

/** 多任务才需要勾选 —— 与后端 dag.needs_confirm（len > 1）保持一致的阈值语义 */
const selectable = computed(() => props.tasks.length > 1)

const doneCount = computed(
  () => props.tasks.filter((t) => t.status === STATE.SUCCEEDED).length,
)

const hasFailure = computed(() => props.tasks.some((t) => t.status === STATE.FAILED))

/** 还有未开始的任务处于 awaiting_confirm 态时，可以"取消后续" */
const canCancelRemaining = computed(() =>
  props.tasks.some((t) => t.status === STATE.QUEUED || t.status === STATE.WAITING),
)

/** 当前被勾选（即未被取消）的任务 id，就是 resume 时要带回去的 approved_ids */
const approvedIds = computed(() =>
  props.tasks.filter((t) => t.status !== STATE.CANCELED).map((t) => t.id),
)

const overallLabel = computed(() => {
  if (hasFailure.value) return 'HAS FAILURE'
  if (props.awaitingConfirm) return 'AWAITING CONFIRM'
  if (props.tasks.some((t) => t.status === STATE.RUNNING)) return 'RUNNING'
  if (doneCount.value === props.tasks.length && props.tasks.length > 0) return 'ALL DONE'
  return 'PENDING'
})

const overallClass = computed(() =>
  hasFailure.value
    ? 'border-[#F5C6C0] bg-[#FDEDEB] text-[#C0392B]'
    : 'border-[#D8D5C9] text-[#5F5E5A]',
)

const overallDotClass = computed(() =>
  hasFailure.value ? 'bg-[#C0392B]' : 'bg-[#0F6E56]',
)

/* ------------------------------------------------------------------ */
/* 展示辅助                                                            */
/* ------------------------------------------------------------------ */

const statusLabel = (status) => STEP_LABEL[status] ?? status ?? '—'
const statusClass = (status) => STEP_CLASS[status] ?? 'border-[#D8D5C9] text-[#5F5E5A]'

/** 工具名 → 人话（查本地库 / 查网络） */
const toolLabel = (tool) =>
  tool === 'web.retrieve_candidates' ? '网络搜索' : '本地知识库'

/** 已完成或已取消的行不允许再改勾选 —— 改了也没有执行机会 */
const isLocked = (task) =>
  task.status === STATE.SUCCEEDED || task.status === STATE.CANCELED

/* ------------------------------------------------------------------ */
/* 单步进度：来自 SSE 的 __research_progress__ 事件                    */
/* ------------------------------------------------------------------ */

/**
 * 每个任务最近一次的进度百分比。
 * 后端 tools/runtime.py 的 ToolProgress.progress 会经由
 * ToolExecutor 的 progress_sink 回放成 research_progress 事件，
 * 前端按 task id 归集到这张表里。
 */
const progressByTask = ref({})
const progressOf = (id) => progressByTask.value[id] ?? 0

const applyProgressEvent = (event) => {
  const taskId = event?.details?.task_id
  if (!taskId) return
  progressByTask.value = { ...progressByTask.value, [taskId]: event.details.progress ?? 0 }
}
defineExpose({ applyProgressEvent })

/* ------------------------------------------------------------------ */
/* ★ R10：轮询兜底                                                     */
/* ------------------------------------------------------------------ */

let timer = null

/**
 * 轮询兜底（照搬参考项目 useAgent.ts:24-26 的 800ms）。
 *
 * 为什么需要：SSE 只推送"它知道的变化"；如果某个任务的状态是在下一次
 * 事件到来之前落库的，卡片就会停在旧状态。轮询用一个固定间隔去拉最新计划，
 * 保证最终一致 —— 代价很低（只是读一次计划），收益是"不会卡在等待中"。
 *
 * TODO(S10): 接上真实接口。后端需要补一个 `GET /api/chat/plan?thread_id=`
 *            返回最新的 {tasks, rationale, iteration}。
 */
const startPolling = () => {
  stopPolling()
  timer = setInterval(() => {
    // TODO(S10): fetchPlan(props.threadId).then((plan) => emit('plan-updated', plan))
  }, 800)
}

const stopPolling = () => {
  if (timer !== null) {
    clearInterval(timer)
    timer = null
  }
}

// 只在"执行中"轮询，跑完/取消完立刻停 —— 避免无意义的请求
watch(
  () => props.tasks.map((t) => t.status).join(','),
  () => {
    const active = props.tasks.some(
      (t) => t.status === STATE.RUNNING || t.status === STATE.QUEUED,
    )
    if (active) startPolling()
    else stopPolling()
  },
  { immediate: true },
)

onBeforeUnmount(stopPolling)
</script>

<!--
===============================================================================
S10 待接线清单（Demo 阶段：组件为骨架，尚未接入 App.vue）
===============================================================================
① backend/app/api/routes_chat.py（约 :206-234 的 __custom__ 分支）
   增加对 kind == "search_plan" 的转发，新增两种 SSE 事件：

   | 事件                     | step 字段                | data 结构                                            |
   | ------------------------ | ------------------------ | ---------------------------------------------------- |
   | 检索计划                 | __search_plan__          | {tasks:[{id,tool,query,channel,note,status}], iteration} |
   | 计划确认暂停（复用现有） | __hitl_pause__           | {kind:"search_plan_review", tasks, prompt}           |
   | 工具级进度（复用现有）   | __research_progress__    | 现有结构 + details.progress + details.task_id       |

② frontend/src/App.vue
   · import SearchPlanCard from './components/SearchPlanCard.vue'
   · 在 SSE 处理里按 step 分发：__search_plan__ → 更新计划卡片
                              __hitl_pause__ → 判 data.kind：
                                 "search_plan_review" → 计划卡片进入确认态
                                 其他（写作前注入式）→ 原有输入框
     ⚠️ 两种确认点必须按 kind 分发渲染，不要共用同一个交互组件，
        否则用户分不清"现在是在勾检索"还是"现在是在补写作要求"。
   · 确认后调 /api/chat/resume，body 带 {thread_id, human_input: "", approved_ids}

③ 视觉验收：与 ResearchProcess.vue 并排放时，边框色 / 字号 / 圆角必须一致
   （本组件刻意不用 rounded，与 ResearchProcess.vue 的方角保持一致）。
===============================================================================
-->
