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
      <p class="input-hint">Enter 发送，Shift + Enter 换行</p>
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
import { ref } from 'vue'

const props = defineProps<{
  modelValue: string
  disabled: boolean
  isProcessing: boolean
  queuedCount: number
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
}
</style>
