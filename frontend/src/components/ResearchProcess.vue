<template>
  <section class="border border-[#D8D5C9] bg-white" aria-label="Research Agent process">
    <header class="flex flex-col gap-3 border-b border-[#E7E4D8] px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
      <div class="flex items-center gap-3">
        <div class="flex h-9 w-9 items-center justify-center bg-[#0F6E56] font-mono text-[11px] font-medium text-white">
          RAG
        </div>
        <div>
          <div class="flex items-center gap-2">
            <h2 class="text-[11px] font-medium uppercase tracking-[0.18em] text-[#0F1115]">Research agent</h2>
            <span class="border border-[#9FE1CB] bg-[#E1F7EF] px-1.5 py-0.5 text-[9px] font-medium tracking-[0.12em] text-[#0F6E56]">
              AGENTIC RAG
            </span>
          </div>
          <p class="mt-1 text-[10px] text-[#888780]">ITERATIVE RETRIEVAL · RERANKING · EVIDENCE CONTROL</p>
        </div>
      </div>

      <div class="flex items-center gap-2 font-mono text-[9px] sm:justify-end">
        <span class="border border-[#D8D5C9] px-2 py-1 text-[#5F5E5A]">PASS {{ pass }}</span>
        <span class="border border-[#D8D5C9] px-2 py-1 text-[#5F5E5A]">ROUND {{ iteration }}</span>
        <span class="border border-[#D8D5C9] px-2 py-1 text-[#5F5E5A]">{{ candidateCount }} CANDIDATES</span>
        <span class="border border-[#D8D5C9] px-2 py-1 text-[#5F5E5A]">{{ evidenceCount }} EVIDENCE</span>
        <span class="inline-flex items-center gap-1.5 border px-2 py-1 tracking-[0.12em]" :class="statusClass">
          <span class="h-1.5 w-1.5 rounded-full" :class="dotClass"></span>
          {{ overallStatus }}
        </span>
      </div>
    </header>

    <div class="px-4 py-4">
      <div class="mb-3 flex min-h-8 items-center justify-between gap-4 border-l-2 px-3 py-1.5" :class="activityClass">
        <div class="min-w-0">
          <p class="truncate text-[10px] font-medium uppercase tracking-[0.12em] text-[#3B3D43]">
            {{ activityTitle }}
          </p>
          <p class="mt-0.5 truncate text-[10px] text-[#888780]">{{ activityMessage }}</p>
        </div>
        <span v-if="latestEvent?.duration_ms !== undefined" class="shrink-0 font-mono text-[9px] text-[#888780]">
          {{ latestEvent.duration_ms }} MS
        </span>
      </div>

      <ol class="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-8">
        <li
          v-for="(stage, index) in stages"
          :key="stage.id"
          class="relative min-h-[108px] border p-3 transition-colors"
          :class="stageCardClass(stage.state.status)"
        >
          <div class="flex items-start justify-between gap-2">
            <span class="font-mono text-[9px] text-[#888780]">{{ String(index + 1).padStart(2, '0') }}</span>
            <span class="inline-flex h-4 min-w-4 items-center justify-center px-1 font-mono text-[8px]" :class="stageBadgeClass(stage.state.status)">
              {{ stageBadge(stage.state.status) }}
            </span>
          </div>
          <h3 class="mt-3 text-[10px] font-medium uppercase leading-tight tracking-[0.08em] text-[#0F1115]">
            {{ stage.title }}
          </h3>
          <p class="mt-1 text-[9px] leading-snug text-[#888780]">{{ stage.description }}</p>
          <div class="mt-2 font-mono text-[8px] uppercase tracking-[0.06em]" :class="stageMetricClass(stage.state.status)">
            {{ stageMetric(stage) }}
          </div>
          <span
            v-if="stage.state.status === 'running'"
            class="absolute bottom-0 left-0 h-0.5 animate-pulse bg-[#1D9E75]"
            style="width: 100%"
          ></span>
        </li>
      </ol>

      <div v-if="coverageGap" class="mt-3 border border-[#EF9F27] bg-[#FAEEDA] px-3 py-2 text-[10px] text-[#854F0B]">
        <span class="font-medium uppercase tracking-[0.1em]">Coverage gap</span>
        <span class="ml-2">{{ coverageGap }}</span>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
  events: {
    type: Array,
    default: () => [],
  },
  active: {
    type: Boolean,
    default: false,
  },
});

const definitions = [
  { id: 'initialize', title: 'Query plan', description: '生成检索词' },
  { id: 'retrieve_local', title: 'Local recall', description: '知识库召回' },
  { id: 'retrieve_web', title: 'Web search', description: '网络候选召回', optional: true },
  { id: 'fuse_candidates', title: 'Fusion', description: '跨来源融合去重' },
  { id: 'rerank_candidates', title: 'Rerank', description: '语义精排证据' },
  { id: 'evaluate_evidence', title: 'Evidence check', description: '充分性与缺口判断' },
  { id: 'refine_query', title: 'Query refine', description: '不足时迭代检索', optional: true },
  { id: 'finalize', title: 'Evidence pack', description: '交付写作上下文' },
];

const latestEvent = computed(() => props.events.at(-1) || null);
const pass = computed(() => latestEvent.value?.pass || 1);
const activeEvents = computed(() => props.events.filter(event => (event.pass || 1) === pass.value));

const stages = computed(() => {
  const states = Object.fromEntries(definitions.map(stage => [stage.id, {
    status: 'pending',
    details: {},
    duration_ms: null,
    visits: 0,
    iteration: 1,
  }]));

  for (const event of activeEvents.value) {
    const state = states[event.stage];
    if (!state) continue;
    if (event.status === 'running') state.visits += 1;
    state.status = event.status || state.status;
    state.details = event.details || state.details;
    state.duration_ms = event.duration_ms ?? state.duration_ms;
    state.iteration = event.iteration || state.iteration;
  }

  return definitions.map(stage => ({ ...stage, state: states[stage.id] }));
});

const iteration = computed(() => Math.max(1, ...activeEvents.value.map(event => Number(event.iteration) || 1)));
const candidateCount = computed(() => {
  const counts = activeEvents.value
    .map(event => Number(event.details?.candidate_count))
    .filter(Number.isFinite);
  return counts.length ? Math.max(...counts) : 0;
});
const evidenceCount = computed(() => {
  const counts = activeEvents.value
    .map(event => Number(event.details?.evidence_count))
    .filter(Number.isFinite);
  return counts.length ? Math.max(...counts) : 0;
});
const coverageGap = computed(() => {
  const event = [...activeEvents.value].reverse().find(item => item.details?.coverage_gap);
  return event?.details?.coverage_gap || '';
});

const overallStatus = computed(() => {
  if (!activeEvents.value.length) return 'WAITING';
  if (activeEvents.value.some(event => event.status === 'failed')) return 'FAILED';
  if (latestEvent.value?.stage === 'finalize' && latestEvent.value?.status === 'completed') return 'COMPLETE';
  if (props.active || latestEvent.value?.status === 'running') return 'LIVE';
  return 'READY';
});

const statusClass = computed(() => ({
  LIVE: 'border-[#1D9E75] text-[#0F6E56]',
  COMPLETE: 'border-[#5DCAA5] text-[#0F6E56]',
  FAILED: 'border-[#E24B4A] text-[#A32D2D]',
  READY: 'border-[#B4B2A9] text-[#5F5E5A]',
  WAITING: 'border-[#D8D5C9] text-[#888780]',
}[overallStatus.value]));

const dotClass = computed(() => ({
  LIVE: 'bg-[#1D9E75] animate-pulse',
  COMPLETE: 'bg-[#1D9E75]',
  FAILED: 'bg-[#E24B4A]',
  READY: 'bg-[#888780]',
  WAITING: 'bg-[#B4B2A9]',
}[overallStatus.value]));

const activityTitle = computed(() => {
  if (!latestEvent.value) return 'Research agent standing by';
  return `Round ${latestEvent.value.iteration || 1} · ${latestEvent.value.label || latestEvent.value.stage}`;
});
const activityMessage = computed(() => latestEvent.value?.message || '等待主流程进入 Research 节点');
const activityClass = computed(() => {
  if (overallStatus.value === 'FAILED') return 'border-[#E24B4A] bg-[#FCEBEB]';
  if (overallStatus.value === 'LIVE') return 'border-[#1D9E75] bg-[#E1F7EF]';
  return 'border-[#B4B2A9] bg-[#F7F6F1]';
});

const stageCardClass = status => ({
  running: 'border-[#1D9E75] bg-[#E1F7EF]',
  completed: 'border-[#9FE1CB] bg-white',
  failed: 'border-[#E24B4A] bg-[#FCEBEB]',
  pending: 'border-[#E7E4D8] bg-[#F7F6F1]',
}[status]);

const stageBadgeClass = status => ({
  running: 'bg-[#0F6E56] text-white',
  completed: 'bg-[#E1F7EF] text-[#0F6E56]',
  failed: 'bg-[#E24B4A] text-white',
  pending: 'bg-[#E7E4D8] text-[#888780]',
}[status]);

const stageMetricClass = status => status === 'failed'
  ? 'text-[#A32D2D]'
  : status === 'pending' ? 'text-[#B4B2A9]' : 'text-[#0F6E56]';

const stageBadge = status => ({
  running: 'LIVE',
  completed: '✓',
  failed: '!',
  pending: '·',
}[status]);

const stageMetric = stage => {
  const { state } = stage;
  if (state.status === 'pending') return stage.optional ? 'CONDITIONAL' : 'QUEUED';
  if (state.status === 'running') return `ROUND ${state.iteration} · RUNNING`;
  if (state.status === 'failed') return 'FAILED';
  const details = state.details || {};
  if (Number.isFinite(Number(details.candidate_count))) return `${details.candidate_count} CANDIDATES`;
  if (Number.isFinite(Number(details.evidence_count))) return `${details.evidence_count} EVIDENCE`;
  if (Number.isFinite(Number(details.query_count))) return `${details.query_count} QUERIES`;
  if (typeof details.sufficient === 'boolean') return details.sufficient ? 'SUFFICIENT' : 'GAP FOUND';
  return state.duration_ms !== null ? `${state.duration_ms} MS` : 'COMPLETE';
};
</script>
