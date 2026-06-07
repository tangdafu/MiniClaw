<template>
  <footer class="chat-input-shell">
    <div class="input-card">
      <textarea
        ref="textareaRef"
        :value="modelValue"
        :placeholder="placeholder"
        rows="1"
        @input="handleInput"
        @keydown.enter.prevent="handleEnter"
      ></textarea>
      <div class="input-actions">
        <button v-if="contextUsage" class="token-meter" type="button" @click="isUsageOpen = true">
          <span class="meter-copy">{{ compactTokenText }}</span>
          <span class="meter-track"><span :style="{ width: `${usagePercent}%` }"></span></span>
        </button>
        <button class="send-button" :disabled="disabled || !modelValue.trim()" @click="$emit('send')">
          {{ isProcessing ? '加入队列' : '发送' }}
        </button>
      </div>
    </div>
    <div class="input-footer">
      <p class="input-hint">Enter 发送，Shift + Enter 换行</p>
      <div v-if="isProcessing || queuedCount > 0" class="run-controls">
        <span>{{ isProcessing ? '正在生成' : '空闲' }}<template v-if="queuedCount > 0"> · 排队 {{ queuedCount }}</template></span>
        <button @click="$emit('cancelCurrent')">停止当前</button>
        <button :disabled="queuedCount === 0" @click="$emit('clearQueue')">清空队列</button>
        <button @click="$emit('stopSession')">全部停止</button>
      </div>
    </div>
    <div v-if="isUsageOpen && contextUsage" class="usage-modal-backdrop" @click="isUsageOpen = false">
      <section class="usage-modal" role="dialog" aria-modal="true" aria-labelledby="usage-title" @click.stop>
        <header>
          <p>Context Budget</p>
          <h3 id="usage-title">上下文使用情况</h3>
          <button type="button" @click="isUsageOpen = false">关闭</button>
        </header>
        <div class="usage-summary">
          <strong>{{ formatTokens(contextUsage.estimated_tokens) }}</strong>
          <span>占触发阈值 {{ usagePercent }}%</span>
        </div>
        <div class="usage-progress"><span :style="{ width: `${usagePercent}%` }"></span></div>
        <dl class="usage-meta">
          <div>
            <dt>触发阈值</dt>
            <dd>{{ formatTokens(contextUsage.trigger_tokens) }}</dd>
          </div>
          <div>
            <dt>压缩目标</dt>
            <dd>{{ formatTokens(contextUsage.target_tokens) }}</dd>
          </div>
          <div>
            <dt>模型消息</dt>
            <dd>{{ contextUsage.model_messages ?? 0 }} 条</dd>
          </div>
          <div>
            <dt>历史消息</dt>
            <dd>{{ contextUsage.history_messages ?? 0 }} 条</dd>
          </div>
        </dl>
        <div class="breakdown-list">
          <div v-for="item in breakdownRows" :key="item.label" class="breakdown-row">
            <div>
              <strong>{{ item.label }}</strong>
              <span>{{ item.description }}</span>
            </div>
            <span>{{ formatTokens(item.value) }}</span>
          </div>
        </div>
        <p class="usage-note">
          {{ contextUsage.compacted ? (contextUsage.cache_hit ? '当前使用已缓存摘要。' : '当前上下文已压缩。') : '当前使用完整会话历史。' }}
        </p>
      </section>
    </div>
  </footer>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ContextUsageEvent } from '../types/chat'

const props = defineProps<{
  modelValue: string
  disabled: boolean
  isProcessing: boolean
  queuedCount: number
  contextUsage?: ContextUsageEvent
  placeholder?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  send: []
  cancelCurrent: []
  clearQueue: []
  stopSession: []
}>()

const textareaRef = ref<HTMLTextAreaElement>()
const isUsageOpen = ref(false)

const usagePercent = computed(() => {
  const used = props.contextUsage?.estimated_tokens ?? 0
  const total = props.contextUsage?.trigger_tokens ?? 0
  if (total <= 0) return 0
  return Math.min(100, Math.round((used / total) * 100))
})

const compactTokenText = computed(() => {
  return `${formatShortTokens(props.contextUsage?.estimated_tokens)} · ${usagePercent.value}%`
})

const breakdownRows = computed(() => {
  const usage = props.contextUsage
  return [
    { label: '系统提示词', description: '动态 system prompt', value: usage?.system_tokens },
    { label: '摘要', description: 'model_context.json 压缩摘要', value: usage?.summary_tokens_breakdown ?? usage?.summary_tokens },
    { label: '用户输入', description: 'role=user 的消息', value: usage?.user_tokens },
    { label: 'Assistant', description: 'assistant 回复和 tool_calls', value: usage?.assistant_tokens },
    { label: '工具返回', description: 'role=tool 的工具结果', value: usage?.tool_tokens },
  ]
})

function handleInput(event: Event) {
  const target = event.target as HTMLTextAreaElement
  emit('update:modelValue', target.value)
  target.style.height = 'auto'
  target.style.height = `${Math.min(target.scrollHeight, 180)}px`
}

function handleEnter(event: KeyboardEvent) {
  if (event.shiftKey || props.disabled || !props.modelValue.trim()) return
  emit('send')
}

function focus() {
  textareaRef.value?.focus()
}

function formatTokens(value?: number): string {
  if (!value) return '0 tokens'
  return `${value.toLocaleString()} tokens`
}

function formatShortTokens(value?: number): string {
  if (!value) return '0'
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`
  return String(value)
}

defineExpose({ focus })
</script>

<style scoped>
.chat-input-shell {
  padding: var(--space-4) var(--space-6) var(--space-5);
  background: linear-gradient(180deg, rgba(248, 250, 252, 0), rgba(248, 250, 252, 0.94) 28%);
}

.input-card {
  display: flex;
  align-items: flex-end;
  gap: var(--space-3);
  padding: 10px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-2xl);
  background: rgba(255, 255, 255, 0.94);
  box-shadow: var(--shadow-soft);
}

textarea {
  flex: 1;
  min-height: 44px;
  max-height: 180px;
  padding: 11px 12px;
  border: 0;
  outline: 0;
  resize: none;
  background: transparent;
  color: var(--text-primary);
  font: inherit;
  font-size: 15px;
  line-height: 1.55;
}

textarea::placeholder {
  color: var(--text-tertiary);
}

.input-actions {
  min-width: 96px;
  display: grid;
  gap: 7px;
}

.token-meter {
  display: grid;
  gap: 5px;
  padding: 7px 9px;
  border: 1px solid #bfdbfe;
  border-radius: var(--radius-lg);
  background: linear-gradient(180deg, #eff6ff, #fff);
  color: #1d4ed8;
  font-size: 11px;
  font-weight: 800;
  cursor: pointer;
}

.token-meter:hover {
  border-color: #60a5fa;
}

.meter-copy {
  text-align: center;
  white-space: nowrap;
}

.meter-track,
.usage-progress {
  height: 5px;
  overflow: hidden;
  border-radius: 999px;
  background: #dbeafe;
}

.meter-track span,
.usage-progress span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #2563eb, #7c3aed);
}

.send-button {
  width: 100%;
  min-width: 82px;
  height: 44px;
  border: 0;
  border-radius: var(--radius-lg);
  background: linear-gradient(135deg, #2563eb, #4f46e5);
  color: #fff;
  font-weight: 800;
  cursor: pointer;
  box-shadow: 0 10px 24px rgba(37, 99, 235, 0.24);
}

.send-button:hover:not(:disabled) {
  transform: translateY(-1px);
}

.send-button:disabled {
  background: #cbd5e1;
  box-shadow: none;
  cursor: not-allowed;
}

.input-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  margin: 8px 14px 0;
}

.input-hint {
  margin: 8px 14px 0;
  color: var(--text-tertiary);
  font-size: 12px;
}

.input-footer .input-hint {
  margin: 0;
}

.run-controls {
  display: flex;
  align-items: center;
  gap: 7px;
  color: var(--text-secondary);
  font-size: 12px;
}

.run-controls button {
  border: 1px solid var(--border);
  border-radius: 999px;
  background: #fff;
  color: var(--text-secondary);
  padding: 4px 8px;
  cursor: pointer;
}

.run-controls button:hover:not(:disabled) {
  border-color: var(--accent-soft);
  color: var(--accent);
}

.run-controls button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.usage-modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: grid;
  place-items: end center;
  padding: var(--space-6);
  background: rgba(15, 23, 42, 0.28);
  backdrop-filter: blur(8px);
}

.usage-modal {
  width: min(560px, 100%);
  display: grid;
  gap: var(--space-4);
  padding: var(--space-5);
  border: 1px solid rgba(191, 219, 254, 0.9);
  border-radius: var(--radius-2xl);
  background: rgba(255, 255, 255, 0.97);
  box-shadow: var(--shadow-soft);
}

.usage-modal header {
  display: flex;
  align-items: start;
  justify-content: space-between;
  gap: var(--space-4);
}

.usage-modal header p {
  margin: 0 0 4px;
  color: #2563eb;
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.usage-modal h3 {
  margin: 0;
  color: var(--text-strong);
  font-size: 20px;
}

.usage-modal header button {
  border: 1px solid var(--border);
  border-radius: 999px;
  background: #fff;
  color: var(--text-secondary);
  padding: 6px 10px;
  cursor: pointer;
}

.usage-summary {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-3);
}

.usage-summary strong {
  color: var(--text-strong);
  font-size: 26px;
  letter-spacing: -0.04em;
}

.usage-summary span,
.usage-note {
  color: var(--text-secondary);
  font-size: 13px;
}

.usage-meta {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin: 0;
}

.usage-meta div {
  padding: 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: #f8fafc;
}

.usage-meta dt {
  color: var(--text-tertiary);
  font-size: 11px;
}

.usage-meta dd {
  margin: 4px 0 0;
  color: var(--text-strong);
  font-size: 13px;
  font-weight: 800;
}

.breakdown-list {
  display: grid;
  gap: 8px;
}

.breakdown-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: 10px 12px;
  border: 1px solid rgba(226, 232, 240, 0.9);
  border-radius: var(--radius-lg);
  background: #fff;
}

.breakdown-row div {
  display: grid;
  gap: 2px;
}

.breakdown-row strong {
  color: var(--text-strong);
  font-size: 13px;
}

.breakdown-row div span {
  color: var(--text-tertiary);
  font-size: 12px;
}

.breakdown-row > span {
  color: #1d4ed8;
  font-size: 13px;
  font-weight: 900;
  white-space: nowrap;
}

.usage-note {
  margin: 0;
}

@media (max-width: 720px) {
  .chat-input-shell {
    padding: var(--space-3);
  }

  .input-card {
    border-radius: var(--radius-xl);
  }

  .input-actions {
    min-width: 82px;
  }

  .usage-modal-backdrop {
    place-items: end stretch;
    padding: var(--space-3);
  }

  .usage-meta {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
