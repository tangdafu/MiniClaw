<template>
  <aside class="session-sidebar">
    <div class="session-brand">
      <div>
        <p class="eyebrow">MiniClaw</p>
        <h2>会话</h2>
      </div>
      <button class="new-session" :disabled="disabled" @click="$emit('create')">
        新建
      </button>
    </div>

    <div class="session-list" aria-label="会话列表">
      <button
        v-for="session in sessions"
        :key="session.session_id"
        class="session-item"
        :class="{ active: session.session_id === activeSessionId }"
        :disabled="disabled"
        @click="$emit('select', session.session_id)"
      >
        <span class="session-main">
          <span class="session-title">{{ session.title }}</span>
          <button
            v-if="session.message_count > 0"
            class="delete-session"
            :disabled="disabled"
            title="删除会话"
            @click.stop="$emit('delete', session.session_id)"
          >
            删除
          </button>
        </span>
        <span class="session-meta">{{ session.message_count }} 条消息 · {{ formatDate(session.updated_at) }}</span>
      </button>

      <div v-if="sessions.length === 0 && !isLoading" class="empty-sessions">
        还没有会话。新建一个开始探索。
      </div>

      <div v-if="isLoading" class="empty-sessions">
        正在加载会话...
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import type { SessionSummary } from '../types/chat'

defineProps<{
  sessions: SessionSummary[]
  activeSessionId: string
  disabled: boolean
  isLoading: boolean
}>()

defineEmits<{
  create: []
  select: [sessionId: string]
  delete: [sessionId: string]
}>()

function formatDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '刚刚'
  return date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}
</script>

<style scoped>
.session-sidebar {
  width: 280px;
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: linear-gradient(180deg, #111827 0%, #0f172a 100%);
  color: #f8fafc;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: var(--radius-2xl);
  box-shadow: var(--shadow-soft);
  overflow: hidden;
}

.session-brand {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-5);
  border-bottom: 1px solid rgba(148, 163, 184, 0.18);
}

.eyebrow {
  margin: 0 0 4px;
  color: #93c5fd;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

h2 {
  margin: 0;
  font-size: 20px;
  letter-spacing: -0.03em;
}

.new-session {
  border: 1px solid rgba(147, 197, 253, 0.42);
  background: rgba(59, 130, 246, 0.18);
  color: #dbeafe;
  border-radius: var(--radius-md);
  padding: 8px 12px;
  font-weight: 700;
  cursor: pointer;
}

.new-session:hover:not(:disabled) {
  background: rgba(59, 130, 246, 0.28);
}

.new-session:disabled,
.session-item:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.session-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-3);
}

.session-item {
  width: 100%;
  display: grid;
  gap: 6px;
  padding: 12px;
  border: 1px solid transparent;
  border-radius: var(--radius-lg);
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.session-item:hover:not(:disabled),
.session-item.active {
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(191, 219, 254, 0.24);
}

.session-item.active {
  box-shadow: inset 3px 0 0 #60a5fa;
}

.session-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #f8fafc;
  font-size: 14px;
  font-weight: 650;
}

.session-main {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.delete-session {
  margin-left: auto;
  flex: 0 0 auto;
  border: 1px solid rgba(248, 113, 113, 0.28);
  border-radius: 999px;
  background: rgba(127, 29, 29, 0.2);
  color: #fecaca;
  padding: 3px 7px;
  font-size: 11px;
  font-weight: 700;
  opacity: 0;
  cursor: pointer;
}

.session-item:hover .delete-session,
.session-item.active .delete-session,
.delete-session:focus-visible {
  opacity: 1;
}

.delete-session:hover:not(:disabled) {
  background: rgba(220, 38, 38, 0.28);
}

.session-meta,
.empty-sessions {
  color: #94a3b8;
  font-size: 12px;
}

.empty-sessions {
  padding: var(--space-4);
  line-height: 1.6;
}

@media (max-width: 820px) {
  .session-sidebar {
    width: 100%;
    max-height: 210px;
  }

  .session-list {
    display: flex;
    gap: var(--space-2);
    overflow-x: auto;
    overflow-y: hidden;
  }

  .session-item {
    min-width: 210px;
  }
}
</style>
