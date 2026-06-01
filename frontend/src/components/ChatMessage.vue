<template>
  <article class="chat-message" :class="[message.role, { error: message.isError }]">
    <div class="avatar">{{ avatarLabel }}</div>
    <div class="message-card">
      <div v-if="message.role === 'user'" class="plain-text">{{ message.content }}</div>
      <div v-else-if="message.isError" class="error-text">{{ message.content }}</div>
      <template v-else>
        <ReasoningBlock v-if="message.reasoning" :reasoning="message.reasoning" />
        <ToolTimeline v-if="message.toolPairs?.length" :tool-pairs="message.toolPairs" />
        <MarkdownContent v-if="message.content" :content="message.content" />
        <div v-else class="stream-placeholder">正在生成回复...</div>
      </template>
    </div>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import MarkdownContent from './MarkdownContent.vue'
import ReasoningBlock from './ReasoningBlock.vue'
import ToolTimeline from './ToolTimeline.vue'
import type { Message } from '../types/chat'

const props = defineProps<{
  message: Message
}>()

const avatarLabel = computed(() => {
  if (props.message.isError) return '!'
  return props.message.role === 'user' ? '你' : 'M'
})

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
