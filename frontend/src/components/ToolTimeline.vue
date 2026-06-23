<template>
  <section class="tool-timeline">
    <button class="timeline-toggle" @click="isOpen = !isOpen">
      <span class="chevron">{{ isOpen ? '⌄' : '›' }}</span>
      <span class="label">工具执行</span>
      <span class="meta">{{ toolPairs.length }} 个工具</span>
    </button>

    <div v-if="isOpen" class="timeline-list">
      <article v-for="(pair, index) in toolPairs" :key="pair.call.toolCallId || index" class="tool-entry">
        <button class="tool-summary" @click="toggle(index)">
          <span class="status-dot" :class="pair.call.status || 'completed'"></span>
          <span class="tool-name">{{ pair.call.name || 'tool' }}</span>
          <span class="tool-state">{{ toolStateLabel(pair.call.status) }}</span>
          <span class="tool-preview">{{ preview(pair.result || pair.call.arguments) }}</span>
          <span class="expand">{{ expanded.has(index) ? '收起' : '详情' }}</span>
        </button>

        <div v-if="expanded.has(index)" class="tool-details">
          <div class="detail-block">
            <div class="detail-label">参数</div>
            <pre>{{ pair.call.arguments || '{}' }}</pre>
          </div>
          <div v-if="pair.call.blockedReason" class="detail-block">
            <div class="detail-label">阻止原因</div>
            <pre>{{ pair.call.blockedReason }}</pre>
          </div>
          <div v-if="pair.call.changedFiles?.length" class="detail-block">
            <div class="detail-label">变更文件</div>
            <pre>{{ pair.call.changedFiles.join('\n') }}</pre>
          </div>
          <div class="detail-block">
            <div class="detail-label">结果</div>
            <pre>{{ pair.result || '无结果' }}</pre>
          </div>
        </div>
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { ToolCall, ToolPair } from '../types/chat'

defineProps<{
  toolPairs: ToolPair[]
}>()

const isOpen = ref(false)
const expanded = ref(new Set<number>())

function toggle(index: number) {
  const next = new Set(expanded.value)
  if (next.has(index)) {
    next.delete(index)
  } else {
    next.add(index)
  }
  expanded.value = next
}

function toolStateLabel(status?: ToolCall['status']): string {
  switch (status) {
    case 'pending':
      return '待执行'
    case 'running':
      return '执行中'
    case 'blocked':
      return '已阻止'
    default:
      return '已完成'
  }
}

function preview(value: string): string {
  const compact = value.replace(/\s+/g, ' ').trim()
  if (!compact) return '已完成'
  return compact.length > 90 ? `${compact.slice(0, 90)}...` : compact
}
</script>

<style scoped>
.tool-timeline {
  margin-bottom: var(--space-3);
  border: 1px solid #bfdbfe;
  border-radius: var(--radius-lg);
  background: #eff6ff;
  overflow: hidden;
}

.timeline-toggle,
.tool-summary {
  width: 100%;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  border: 0;
  background: transparent;
  cursor: pointer;
  text-align: left;
}

.timeline-toggle {
  padding: 9px 11px;
  color: #1d4ed8;
  font-size: 13px;
}

.label,
.tool-name {
  font-weight: 700;
}

.meta,
.expand {
  margin-left: auto;
  color: #2563eb;
  font-size: 12px;
}

.chevron {
  font-size: 17px;
  line-height: 1;
}

.timeline-list {
  display: grid;
  gap: 1px;
  background: #bfdbfe;
  border-top: 1px solid #bfdbfe;
}

.tool-entry {
  background: #f8fbff;
}

.tool-summary {
  padding: 10px 12px;
  color: var(--text-primary);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: #22c55e;
  box-shadow: 0 0 0 4px rgba(34, 197, 94, 0.12);
  flex: 0 0 auto;
}

.status-dot.pending,
.status-dot.running {
  background: #f59e0b;
  box-shadow: 0 0 0 4px rgba(245, 158, 11, 0.12);
}

.status-dot.blocked {
  background: #ef4444;
  box-shadow: 0 0 0 4px rgba(239, 68, 68, 0.12);
}

.tool-state {
  color: #2563eb;
  font-size: 12px;
  font-weight: 700;
}

.tool-preview {
  min-width: 0;
  overflow: hidden;
  color: var(--text-secondary);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-details {
  display: grid;
  gap: var(--space-3);
  padding: 0 12px 12px 30px;
}

.detail-label {
  margin-bottom: 5px;
  color: var(--text-tertiary);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

pre {
  max-height: 280px;
  overflow: auto;
  margin: 0;
  padding: 10px;
  border-radius: var(--radius-md);
  background: #0f172a;
  color: #dbeafe;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
