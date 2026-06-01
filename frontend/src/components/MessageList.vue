<template>
  <div ref="containerRef" class="message-list" @scroll="handleScroll">
    <div v-if="isLoadingHistory" class="history-status">正在加载更早的消息...</div>
    <div v-else-if="hasMore" class="history-status subtle">向上滚动加载更早消息</div>

    <div v-if="messages.length === 0 && !isLoadingHistory" class="empty-chat">
      <div class="empty-card">
        <p class="empty-kicker">Ready</p>
        <h2>开始一个新的 Agent 会话</h2>
        <p>可以让 MiniClaw 分析项目、调用工具、整理上下文，或继续探索已有会话。</p>
      </div>
    </div>

    <ChatMessage v-for="(message, index) in messages" :key="index" :message="message" />

    <div v-if="isGenerating" class="generation-status">
      <span></span><span></span><span></span>
      <strong>MiniClaw 正在响应</strong>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick } from 'vue'
import ChatMessage from './ChatMessage.vue'
import type { Message } from '../types/chat'

defineProps<{
  messages: Message[]
  isLoadingHistory: boolean
  hasMore: boolean
  isGenerating: boolean
}>()

const emit = defineEmits<{
  loadOlder: []
}>()

const containerRef = ref<HTMLDivElement>()

function handleScroll() {
  const container = containerRef.value
  if (!container || container.scrollTop > 90) return
  emit('loadOlder')
}

function getScrollHeight(): number {
  return containerRef.value?.scrollHeight ?? 0
}

function restoreScrollAfterPrepend(previousHeight: number) {
  const container = containerRef.value
  if (container) {
    container.scrollTop = container.scrollHeight - previousHeight
  }
}

function scrollToBottom() {
  void nextTick(() => {
    const container = containerRef.value
    if (container) {
      container.scrollTop = container.scrollHeight
    }
  })
}

defineExpose({ getScrollHeight, restoreScrollAfterPrepend, scrollToBottom })
</script>

<style scoped>
.message-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  padding: var(--space-6);
  scroll-behavior: smooth;
}

.history-status {
  align-self: center;
  padding: 7px 12px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.75);
  color: var(--text-secondary);
  font-size: 12px;
}

.history-status.subtle {
  color: var(--text-tertiary);
}

.empty-chat {
  flex: 1;
  display: grid;
  place-items: center;
  min-height: 320px;
}

.empty-card {
  max-width: 460px;
  padding: 32px;
  border: 1px solid var(--border);
  border-radius: var(--radius-2xl);
  background: rgba(255, 255, 255, 0.78);
  box-shadow: var(--shadow-soft);
  text-align: center;
}

.empty-kicker {
  margin: 0 0 8px;
  color: var(--accent);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.empty-card h2 {
  margin: 0 0 10px;
  color: var(--text-strong);
  font-size: 24px;
  letter-spacing: -0.04em;
}

.empty-card p:last-child {
  margin: 0;
  color: var(--text-secondary);
  line-height: 1.7;
}

.generation-status {
  align-self: flex-start;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 10px 13px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.86);
  color: var(--text-secondary);
  font-size: 13px;
  box-shadow: var(--shadow-xs);
}

.generation-status span {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: var(--accent);
  animation: pulse 1.2s infinite ease-in-out;
}

.generation-status span:nth-child(2) { animation-delay: 0.15s; }
.generation-status span:nth-child(3) { animation-delay: 0.3s; }

@keyframes pulse {
  0%, 80%, 100% { opacity: 0.35; transform: translateY(0); }
  40% { opacity: 1; transform: translateY(-2px); }
}

@media (max-width: 720px) {
  .message-list {
    padding: var(--space-4);
    gap: var(--space-4);
  }
}
</style>
