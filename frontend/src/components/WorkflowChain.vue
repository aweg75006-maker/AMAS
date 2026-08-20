<!--
工作流思维链：横向 5 步展示（planner → researcher → writer → reviewer → done）

设计要点：
- 替代旧 StatusFlow.vue（垂直小卡片，位于左栏底部），改为右侧主区顶部的大尺寸横向 stepper
- 当前步骤：深色高亮 + 脉冲点 + 略放大
- 已完成：绿色 ✓ + 反显色
- 未开始：浅灰描边
- paused：amber 闪烁 + 全部 step 降低饱和度
- 不引入新的 SVG，全部用 lucide-vue-next 图标（保持依赖最小）
-->
<template>
  <div class="wf-panel">
    <div class="wf-head">
      <span class="wf-eyebrow">Workflow engine</span>
      <div class="wf-head-right">
        <span class="wf-status" :class="`wf-status-${statusKey}`">
          <span class="wf-dot"></span>
          {{ statusLabel }}
        </span>
      </div>
    </div>

    <div class="wf-chain">
      <template v-for="(step, i) in steps" :key="step.id">
        <button
          class="wf-step"
          :class="stepClass(i)"
          :title="step.label"
          type="button"
        >
          <span class="wf-step-icon">
            <CheckIcon v-if="isDone(i)" :size="22" />
            <Loader2Icon v-else-if="isActive(i)" :size="22" class="wf-spin" />
            <component v-else :is="step.icon" :size="22" />
          </span>
          <span class="wf-step-meta">
            <span class="wf-step-num">0{{ i + 1 }}</span>
            <span class="wf-step-label">{{ step.label }}</span>
            <span class="wf-step-desc">{{ step.desc }}</span>
          </span>
        </button>

        <span class="wf-arrow" :class="{ 'wf-arrow-on': isDone(i) || isActive(i) }" aria-hidden="true">
          <ChevronRight :size="18" />
        </span>
      </template>

      <button
        class="wf-step wf-step-final"
        :class="doneClass()"
        type="button"
      >
        <span class="wf-step-icon">
          <FlagIcon v-if="currentStep === 'done'" :size="22" />
          <CircleDashedIcon v-else :size="22" />
        </span>
        <span class="wf-step-meta">
          <span class="wf-step-num">05</span>
          <span class="wf-step-label">REPORT</span>
          <span class="wf-step-desc">最终报告交付</span>
        </span>
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue';
import {
  CheckIcon,
  Loader2Icon,
  ChevronRight,
  FlagIcon,
  CircleDashedIcon,
  BrainCircuitIcon,
  SearchIcon,
  FileTextIcon,
  ShieldCheckIcon,
} from 'lucide-vue-next';

const props = defineProps({
  currentStep: { type: String, default: 'idle' },
});

// 五个语义步骤：planner → researcher → writer → reviewer → (done 单独渲染在右侧)
const steps = [
  { id: 'planner', label: 'TASK PLANNING', desc: '拆解任务与路径规划', icon: BrainCircuitIcon },
  { id: 'researcher', label: 'DEEP SEARCH', desc: '全网数据检索与聚合', icon: SearchIcon },
  { id: 'writer', label: 'CONTENT GENERATION', desc: '多维信息整合与写作', icon: FileTextIcon },
  { id: 'reviewer', label: 'QUALITY ASSURANCE', desc: '逻辑校验与反思修正', icon: ShieldCheckIcon },
];

const workflowStep = computed(() => props.currentStep === 'refiner' ? 'writer' : props.currentStep);

// 暂停时保留最后一个活跃节点，避免状态退回到第一步。
const lastActiveId = ref('planner');
watch(
  workflowStep,
  (step) => {
    if (steps.some((item) => item.id === step)) lastActiveId.value = step;
  },
  { immediate: true },
);

// 步骤索引（-1=未开始；>=steps.length=全部完成）
const currentStepIndex = computed(() => {
  if (workflowStep.value === 'idle') return -1;
  if (workflowStep.value === 'done') return steps.length;
  if (workflowStep.value === 'paused') {
    // 暂停时复用 currentStep 的索引（保持高亮位置）
    const i = steps.findIndex((s) => s.id === lastActiveId.value);
    return i;
  }
  return steps.findIndex((s) => s.id === workflowStep.value);
});

// === 状态判断辅助函数 ===
const isDone = (i) => props.currentStep === 'done' || currentStepIndex.value > i;
const isActive = (i) =>
  props.currentStep !== 'done' && props.currentStep !== 'paused' && currentStepIndex.value === i;

// === 卡片样式类 ===
const stepClass = (i) => {
  if (props.currentStep === 'paused' && currentStepIndex.value === i) return 'wf-step-paused';
  if (isDone(i)) return 'wf-step-done';
  if (isActive(i)) return 'wf-step-active';
  return 'wf-step-idle';
};
const doneClass = () =>
  props.currentStep === 'done' ? 'wf-step-done' : 'wf-step-idle';

// === 顶部状态徽章 ===
const statusKey = computed(() => {
  if (props.currentStep === 'done') return 'done';
  if (props.currentStep === 'paused') return 'paused';
  if (props.currentStep === 'idle') return 'idle';
  return 'running';
});
const statusLabel = computed(() => {
  switch (statusKey.value) {
    case 'done': return 'COMPLETE';
    case 'paused': return 'PAUSED';
    case 'idle': return 'STANDBY';
    default: return 'RUNNING';
  }
});
</script>

<style scoped>
.wf-panel {
  background: #fff;
  border: 1px solid #D8D5C9;
  padding: 22px 26px 26px;
}
.wf-head {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 18px;
}
.wf-eyebrow {
  font: 500 11px/1 'JetBrains Mono', monospace;
  letter-spacing: .2em; text-transform: uppercase;
  color: #888780;
}
.wf-head-right { display: flex; align-items: center; gap: 12px; }
.wf-status {
  display: inline-flex; align-items: center; gap: 7px;
  padding: 5px 11px;
  border: 1px solid #D8D5C9;
  font: 500 11px/1 'JetBrains Mono', monospace;
  color: #3B3D43;
  letter-spacing: .12em;
}
.wf-status-running { color: #0F1115; border-color: #0F1115; }
.wf-status-running .wf-dot { background: #0F6E56; animation: wf-pulse 1.6s ease-in-out infinite; }
.wf-status-paused { color: #BA7517; border-color: #BA7517; }
.wf-status-paused .wf-dot { background: #BA7517; animation: wf-pulse 1.2s ease-in-out infinite; }
.wf-status-done { color: #0F6E56; border-color: #0F6E56; }
.wf-status-done .wf-dot { background: #0F6E56; }
.wf-status-idle .wf-dot { background: #888780; }
.wf-dot { width: 7px; height: 7px; border-radius: 50%; }
@keyframes wf-pulse { 0%,100%{opacity:1} 50%{opacity:.35} }

/* === 链式卡片 === */
.wf-chain {
  display: flex; align-items: stretch;
  gap: 8px;
}
.wf-step {
  flex: 1;
  min-width: 0;
  display: flex; flex-direction: column; align-items: flex-start;
  gap: 10px;
  padding: 14px;
  border: 1px solid #E7E4D8;
  background: #F7F6F1;
  text-align: left;
  cursor: default;
  transition: background .2s, border-color .2s, transform .2s;
  font-family: inherit;
}
.wf-step-idle { color: #B4B2A9; }
.wf-step-idle .wf-step-num,
.wf-step-idle .wf-step-label { color: #B4B2A9; }
.wf-step-idle .wf-step-desc { color: #B4B2A9; }
.wf-step-idle .wf-step-icon {
  background: #FFF; color: #B4B2A9;
  border: 1px solid #E7E4D8;
}
.wf-step-active {
  background: #0F1115; color: #F7F6F1;
  border-color: #0F1115;
  transform: translateY(-2px);
}
.wf-step-active .wf-step-icon {
  background: #F7F6F1; color: #0F1115;
  border: 1px solid #F7F6F1;
  animation: wf-pulse 1.6s ease-in-out infinite;
}
.wf-step-done {
  background: #FFF; color: #0F6E56;
  border-color: #0F6E56;
}
.wf-step-done .wf-step-icon {
  background: #0F6E56; color: #FFF;
  border: 1px solid #0F6E56;
}
.wf-step-done .wf-step-num,
.wf-step-done .wf-step-label { color: #0F6E56; }
.wf-step-paused {
  background: #FAEEDA; color: #BA7517;
  border-color: #BA7517;
}
.wf-step-paused .wf-step-icon {
  background: #BA7517; color: #FFF;
  border: 1px solid #BA7517;
  animation: wf-pulse 1.2s ease-in-out infinite;
}

/* === 卡片内部 === */
.wf-step-icon {
  flex: 0 0 40px;
  width: 40px; height: 40px;
  display: inline-flex; align-items: center; justify-content: center;
  border-radius: 0;
}
.wf-step-meta { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.wf-step-num {
  font: 500 10px/1 'JetBrains Mono', monospace;
  color: #888780; letter-spacing: .14em;
}
.wf-step-label {
  font-size: 12px; font-weight: 600; line-height: 1.25; color: #0F1115;
  min-height: 30px;
}
.wf-step-desc {
  font-size: 10px; line-height: 1.35; color: #888780;
}
.wf-step-active .wf-step-num { color: #888780; }
.wf-step-active .wf-step-label { color: #F7F6F1; }
.wf-step-active .wf-step-desc { color: #B4B2A9; }

/* === 连接箭头 === */
.wf-arrow {
  display: inline-flex; align-items: center; justify-content: center;
  color: #B4B2A9;
  width: 22px; flex: 0 0 22px;
}
.wf-arrow-on { color: #0F6E56; }

/* === 最终步骤（REPORT）容器样式（沿用 step 样式即可） === */
.wf-step-final { /* 与普通 step 样式一致，靠 className 切换 */ }

@media (max-width: 1180px) {
  .wf-panel { padding: 18px; }
  .wf-chain { gap: 6px; }
  .wf-step { padding: 12px 10px; }
  .wf-step-icon { width: 34px; height: 34px; flex-basis: 34px; }
  .wf-arrow { width: 14px; flex-basis: 14px; }
  .wf-step-desc { display: none; }
}

@media (max-width: 680px) {
  .wf-panel { padding: 16px; overflow: hidden; }
  .wf-chain {
    overflow-x: auto;
    padding-bottom: 8px;
    scroll-snap-type: x proximity;
  }
  .wf-step { flex: 0 0 132px; scroll-snap-align: start; }
}
</style>
