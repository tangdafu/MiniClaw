<template>
  <article class="chat-message" :class="[message.role, { error: message.isError }]">
    <div class="avatar">{{ avatarLabel }}</div>
    <div class="message-card">
      <div v-if="message.role === 'user'" class="plain-text">{{ message.content }}</div>
      <div v-else-if="message.isError" class="error-text">{{ message.content }}</div>
      <template v-else>
        <ReasoningBlock v-if="message.reasoning" :reasoning="message.reasoning" />
        <section v-if="message.compressionEvents?.length" class="compression-block">
          <button class="compression-title" @click="isCompressionOpen = !isCompressionOpen">
            <span>{{ isCompressionOpen ? '⌄' : '›' }}</span>
            上下文压缩
            <small>{{ message.compressionEvents.length }} 个阶段</small>
          </button>
          <ul v-if="isCompressionOpen">
            <li v-for="(event, index) in message.compressionEvents" :key="index">
              <strong>{{ event.stage }}</strong>
              <span>{{ compressionDetail(event) }}</span>
            </li>
          </ul>
        </section>
        <ToolTimeline v-if="message.toolPairs?.length" :tool-pairs="message.toolPairs" />
        <MarkdownContent v-if="message.content" :content="message.content" />
        <div v-else class="stream-placeholder">{{ placeholderText }}</div>
      </template>
    </div>
  </article>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import MarkdownContent from './MarkdownContent.vue'
import ReasoningBlock from './ReasoningBlock.vue'
import ToolTimeline from './ToolTimeline.vue'
import type { CompressionEvent, Message } from '../types/chat'

const props = defineProps<{
  message: Message
}>()

const isCompressionOpen = ref(false)

const avatarLabel = computed(() => {
  if (props.message.isError) return '!'
  return props.message.role === 'user' ? '你' : 'M'
})

const placeholderText = computed(() => {
  if (props.message.status === 'queued') return '已加入队列，等待执行...'
  if (props.message.status === 'cancelled') return '已停止生成'
  return '正在生成回复...'
})

function compressionDetail(event: CompressionEvent): string {
  const parts = []
  if (event.reason) parts.push(event.reason)
  if (event.estimated_tokens) parts.push(`估算 ${event.estimated_tokens}`)
  if (event.head_messages !== undefined && event.tail_messages !== undefined) {
    parts.push(`压缩 ${event.head_messages} 条，保留 ${event.tail_messages} 条`)
  }
  if (event.summary_tokens) parts.push(`摘要 ${event.summary_tokens}`)
  if (event.estimated_tokens_after) parts.push(`压缩后 ${event.estimated_tokens_after}`)
  if (event.detail) parts.push(event.detail)
  return parts.join(' · ')
}

</script>

<style scoped>
.chat-message {
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr);
  gap: var(--space-3);
  align-items: start;
}

.chat-message.user {
  grid-template-columns: minmax(0, 1fr) 36px;
}

.chat-message.user .avatar {
  grid-column: 2;
  grid-row: 1;
  background: linear-gradient(135deg, #2563eb, #7c3aed);
  color: #fff;
}

.chat-message.user .message-card {
  grid-column: 1;
  justify-self: end;
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
  color: #fff;
  border-color: rgba(37, 99, 235, 0.35);
}

.chat-message.error .avatar {
  background: #fee2e2;
  color: #b91c1c;
}

.chat-message.error .message-card {
  background: #fff1f2;
  border-color: #fecdd3;
}

.avatar {
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  border-radius: 14px;
  background: #e0f2fe;
  color: #0369a1;
  font-size: 13px;
  font-weight: 800;
  box-shadow: var(--shadow-xs);
}

.message-card {
  max-width: min(780px, 100%);
  min-width: 0;
  padding: 14px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  background: rgba(255, 255, 255, 0.92);
  box-shadow: var(--shadow-xs);
}

.plain-text,
.error-text {
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

.error-text {
  color: #be123c;
  font-family: var(--font-mono);
  font-size: 13px;
}

.stream-placeholder {
  color: var(--text-tertiary);
  font-size: 14px;
}

.compression-block {
  margin-bottom: var(--space-3);
  border: 1px solid #fde68a;
  border-radius: var(--radius-lg);
  background: #fffbeb;
  overflow: hidden;
}

.compression-title {
  width: 100%;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 9px 11px;
  border: 0;
  background: transparent;
  color: #92400e;
  font-size: 13px;
  font-weight: 800;
  cursor: pointer;
}

.compression-title small {
  margin-left: auto;
  color: #b45309;
}

.compression-block ul {
  display: grid;
  gap: 6px;
  margin: 0;
  padding: 0 12px 12px 30px;
  color: #78350f;
  font-size: 12px;
}

.compression-block li span {
  margin-left: 6px;
  color: #92400e;
}

@media (max-width: 720px) {
  .chat-message,
  .chat-message.user {
    grid-template-columns: 30px minmax(0, 1fr);
  }

  .chat-message.user .avatar {
    grid-column: 1;
  }

  .chat-message.user .message-card {
    grid-column: 2;
    justify-self: stretch;
  }

  .avatar {
    width: 30px;
    height: 30px;
    border-radius: 11px;
  }
}
</style>
