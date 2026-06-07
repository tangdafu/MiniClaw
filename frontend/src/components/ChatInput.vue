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
      <button class="send-button" :disabled="disabled || !modelValue.trim()" @click="$emit('send')">
        {{ isProcessing ? '加入队列' : '发送' }}
      </button>
    </div>
    <div class="input-footer">
      <div class="footer-left">
        <p class="input-hint">Enter 发送，Shift + Enter 换行</p>
        <button v-if="contextUsage" class="token-meter" type="button" @click="$emit('showContextUsage')">
          <span>上下文 {{ compactTokenText }}</span>
          <span class="meter-track"><span :style="{ width: `${usagePercent}%` }"></span></span>
        </button>
      </div>
      <div v-if="isProcessing || queuedCount > 0" class="run-controls">
        <span>{{ isProcessing ? '正在生成' : '空闲' }}<template v-if="queuedCount > 0"> · 排队 {{ queuedCount }}</template></span>
        <button @click="$emit('cancelCurrent')">停止当前</button>
        <button :disabled="queuedCount === 0" @click="$emit('clearQueue')">清空队列</button>
        <button @click="$emit('stopSession')">全部停止</button>
      </div>
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
  showContextUsage: []
}>()

const textareaRef = ref<HTMLTextAreaElement>()

const usagePercent = computed(() => {
  const used = props.contextUsage?.estimated_tokens ?? 0
  const total = props.contextUsage?.trigger_tokens ?? 0
  if (total <= 0) return 0
  return Math.min(100, Math.round((used / total) * 100))
})

const compactTokenText = computed(() => {
  return `${formatShortTokens(props.contextUsage?.estimated_tokens)} · ${usagePercent.value}%`
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

.token-meter {
  min-width: 120px;
  display: inline-grid;
  grid-template-columns: minmax(0, 1fr) 44px;
  align-items: center;
  gap: 8px;
  padding: 5px 8px;
  border: 1px solid #bfdbfe;
  border-radius: 999px;
  background: linear-gradient(180deg, #eff6ff, #fff);
  color: #1d4ed8;
  font-size: 11px;
  font-weight: 800;
  cursor: pointer;
}

.token-meter:hover {
  border-color: #60a5fa;
}

.meter-track {
  height: 5px;
  overflow: hidden;
  border-radius: 999px;
  background: #dbeafe;
}

.meter-track span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #2563eb, #7c3aed);
}

.send-button {
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

.footer-left {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
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

@media (max-width: 720px) {
  .chat-input-shell {
    padding: var(--space-3);
  }

  .input-card {
    border-radius: var(--radius-xl);
  }

  .input-footer {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
