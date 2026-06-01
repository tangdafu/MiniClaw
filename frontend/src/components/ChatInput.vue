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
        {{ isProcessing ? '发送中' : '发送' }}
      </button>
    </div>
    <p class="input-hint">Enter 发送，Shift + Enter 换行</p>
  </footer>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  modelValue: string
  disabled: boolean
  isProcessing: boolean
  placeholder?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  send: []
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

.input-hint {
  margin: 8px 14px 0;
  color: var(--text-tertiary);
  font-size: 12px;
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
