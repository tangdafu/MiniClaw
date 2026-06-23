<template>
  <div class="chat-workspace" :class="{ 'usage-open': usagePanelOpen && activeRuntime.contextUsage }">
    <SessionSidebar
      :sessions="sessions"
      :active-session-id="sessionId"
      :disabled="isLoadingSessions"
      :is-loading="isLoadingSessions"
      :running-session-ids="runningSessionIds"
      :queued-counts="queuedCounts"
      @create="createNewSession"
      @select="selectSession"
      @delete="deleteSession"
    />

    <section class="chat-panel">
      <header class="panel-header">
        <div>
          <p class="panel-kicker">Agent Workspace</p>
          <h2>{{ activeTitle }}</h2>
        </div>
        <div class="connection-pill" :class="{ connected: isConnected }">
          <span></span>
          {{ isConnected ? '已连接' : '连接中' }}
        </div>
      </header>

      <div v-if="globalError" class="global-error">
        <strong>出现问题</strong>
        <span>{{ globalError }}</span>
        <button @click="globalError = ''">关闭</button>
      </div>

      <MessageList
        ref="messageListRef"
        :messages="activeMessages"
        :is-loading-history="activeRuntime.isLoadingHistory"
        :has-more="activeRuntime.hasMore"
        :is-generating="activeRuntime.isProcessing"
        @load-older="loadOlderMessages"
      />

      <ChatInput
        ref="chatInputRef"
        v-model="inputText"
        :disabled="!isConnected || !sessionId"
        :is-processing="activeRuntime.isProcessing"
        :queued-count="activeRuntime.queuedCount"
        :context-usage="activeRuntime.contextUsage"
        placeholder="向 MiniClaw 提问，或描述你想完成的任务..."
        @send="sendMessage"
        @cancel-current="cancelCurrentRun"
        @clear-queue="clearActiveQueue"
        @stop-session="stopActiveSession"
        @show-context-usage="usagePanelOpen = true"
      />
    </section>

    <aside v-if="usagePanelOpen && activeContextUsage" class="usage-panel" aria-label="上下文压缩详情">
      <header>
        <div>
          <p>Context Budget</p>
          <h3>上下文压缩详情</h3>
        </div>
        <button type="button" @click="usagePanelOpen = false">关闭</button>
      </header>
      <div class="usage-summary">
        <strong>{{ formatTokens(activeContextUsage.estimated_tokens) }}</strong>
        <span>占触发阈值 {{ usagePercent }}%</span>
      </div>
      <div class="usage-progress"><span :style="{ width: `${usagePercent}%` }"></span></div>
      <dl class="usage-meta">
        <div>
          <dt>触发阈值</dt>
          <dd>{{ formatTokens(activeContextUsage.trigger_tokens) }}</dd>
        </div>
        <div>
          <dt>压缩目标</dt>
          <dd>{{ formatTokens(activeContextUsage.target_tokens) }}</dd>
        </div>
        <div>
          <dt>模型消息</dt>
          <dd>{{ activeContextUsage.model_messages ?? 0 }} 条</dd>
        </div>
        <div>
          <dt>历史消息</dt>
          <dd>{{ activeContextUsage.history_messages ?? 0 }} 条</dd>
        </div>
      </dl>
      <div class="breakdown-list">
        <div v-for="item in usageBreakdownRows" :key="item.label" class="breakdown-row">
          <div>
            <strong>{{ item.label }}</strong>
            <span>{{ item.description }}</span>
          </div>
          <span>{{ formatTokens(item.value) }}</span>
        </div>
      </div>
      <section v-if="activePruningEvents.length" class="pruning-section">
        <div class="pruning-heading">
          <h4>工具结果剪枝</h4>
          <span>{{ activePruningEvents.length }} 条</span>
        </div>
        <div class="pruning-list">
          <div v-for="event in activePruningEvents" :key="pruningEventKey(event)" class="pruning-card">
            <div>
              <strong>{{ event.tool_name || 'tool' }}</strong>
              <code>{{ event.prune_id }}</code>
            </div>
            <dl>
              <span>原始 {{ formatTokens(event.original_tokens) }}</span>
              <span>保留 {{ formatTokens(event.retained_tokens) }}</span>
              <span>省略 {{ formatTokens(event.omitted_tokens) }}</span>
            </dl>
          </div>
        </div>
      </section>
      <p class="usage-note">
        {{ activeContextUsage.compacted ? (activeContextUsage.cache_hit ? '当前使用已缓存摘要。' : '当前上下文已压缩。') : '当前使用完整会话历史。' }}
      </p>
    </aside>

    <div v-if="activePermissionRequest" class="modal-backdrop" @click.stop>
      <section class="delete-modal permission-modal" role="dialog" aria-modal="true" aria-labelledby="permission-title" @click.stop>
        <div class="delete-icon">权</div>
        <div class="delete-copy">
          <p class="modal-kicker">工具权限</p>
          <h3 id="permission-title">允许执行这个工具吗？</h3>
          <p class="delete-session-name">{{ activePermissionRequest.tool_name }}</p>
          <p class="delete-description">
            风险级别：{{ activePermissionRequest.risk_level || 'unknown' }}
            <span v-if="activePermissionRequest.category"> · 分类：{{ activePermissionRequest.category }}</span>
          </p>
          <p class="permission-note">会话级策略仅在当前会话有效，后端重启或删除会话后失效。</p>
          <pre class="permission-arguments">{{ activePermissionRequest.arguments }}</pre>
        </div>
        <div class="modal-actions permission-actions">
          <button class="secondary-action" :disabled="permissionRequestBusy" @click="resolveToolPermission(activePermissionRequest.request_id, 'deny_once')">拒绝一次</button>
          <button class="secondary-action" :disabled="permissionRequestBusy" @click="resolveToolPermission(activePermissionRequest.request_id, 'deny_session')">本会话始终拒绝</button>
          <button class="secondary-action" :disabled="permissionRequestBusy" @click="resolveToolPermission(activePermissionRequest.request_id, 'allow_once')">允许一次</button>
          <button class="danger-action" :disabled="permissionRequestBusy" @click="resolveToolPermission(activePermissionRequest.request_id, 'allow_session')">本会话始终允许</button>
        </div>
      </section>
    </div>

    <div v-if="deleteTarget" class="modal-backdrop" @click="cancelDelete">
      <section class="delete-modal" role="dialog" aria-modal="true" aria-labelledby="delete-title" @click.stop>
        <div class="delete-icon">删</div>
        <div class="delete-copy">
          <p class="modal-kicker">危险操作</p>
          <h3 id="delete-title">删除这个会话？</h3>
          <p class="delete-session-name">{{ deleteTarget.title }}</p>
          <p class="delete-description">删除后，该会话里的聊天记录会被永久移除，当前版本无法恢复。</p>
        </div>
        <div class="modal-actions">
          <button class="secondary-action" @click="cancelDelete">取消</button>
          <button class="danger-action" @click="confirmDeleteSession">删除</button>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import ChatInput from './ChatInput.vue'
import MessageList from './MessageList.vue'
import SessionSidebar from './SessionSidebar.vue'
import { createOptimisticUserMessage, createRuntimeState, normalizeMessage, useSessionRuntimeState } from '../composables/useSessionRuntimeState'
import { useChatSessions } from '../composables/useChatSessions'
import { useContextUsagePanel, useMessageHistory } from '../composables/useMessageHistory'
import { useChatTransport } from '../composables/useChatTransport'
import type { SessionSummary } from '../types/chat'

const sessions = ref<SessionSummary[]>([])
const inputText = ref('')
const isConnected = ref(false)
const isLoadingSessions = ref(false)
const globalError = ref('')
const sessionId = ref('')
const messageListRef = ref<InstanceType<typeof MessageList>>()
const chatInputRef = ref<InstanceType<typeof ChatInput>>()
const deleteTarget = ref<SessionSummary | null>(null)
const permissionRequestBusy = ref(false)

const {
  sessionStates,
  activeRuntime,
  activeMessages,
  activeContextUsage,
  activePruningEvents,
  activePermissionRequest,
  runningSessionIds,
  queuedCounts,
  ensureSessionState,
  ensureAssistantForRun,
  clearPendingPermissionRequestsForRun,
  clearPendingToolCallsForRun,
  upsertPruningEvent,
  pruningEventKey,
  markQueuedMessagesCancelled,
} = useSessionRuntimeState(sessionId)

const {
  loadSessions,
  createNewSession,
  selectSession,
  deleteSession,
  cancelDelete,
  confirmDeleteSession,
  fetchJson,
} = useChatSessions({
  sessions,
  sessionId,
  sessionStates,
  isLoadingSessions,
  globalError,
  deleteTarget,
  createRuntimeState,
  getLoadContextUsage: () => loadContextUsage,
  getLoadLatestMessages: () => loadLatestMessages,
  focusInput: () => {
    void nextTick()
    chatInputRef.value?.focus()
  },
})

const {
  usagePanelOpen,
  loadContextUsage,
  usagePercent,
  usageBreakdownRows,
} = useContextUsagePanel({
  activeRuntime,
  ensureSessionState,
  fetchJson,
})

const {
  loadRunSummary,
  loadLatestMessages,
  loadOlderMessages,
} = useMessageHistory({
  sessionId,
  globalError,
  messageListRef,
  ensureSessionState,
  normalizeMessage,
  fetchJson,
  loadContextUsage,
})

const {
  connectWebSocket,
  sendMessage,
  sendControl,
  resolveToolPermission,
  dispose,
} = useChatTransport({
  sessionId,
  globalError,
  inputText,
  isConnected,
  permissionRequestBusy,
  messageListRef,
  ensureSessionState,
  ensureAssistantForRun,
  clearPendingPermissionRequestsForRun,
  clearPendingToolCallsForRun,
  upsertPruningEvent,
  markQueuedMessagesCancelled,
  createOptimisticUserMessage,
  loadRunSummary,
  loadSessions,
})

const activeTitle = computed(() => {
  return sessions.value.find((session) => session.session_id === sessionId.value)?.title || '新会话'
})

function cancelCurrentRun() {
  sendControl('cancel_current')
}

function clearActiveQueue() {
  sendControl('clear_queue')
}

function stopActiveSession() {
  sendControl('stop_session')
}

function formatTokens(value?: number): string {
  if (!value) return '0 tokens'
  return `${value.toLocaleString()} tokens`
}

onMounted(() => {
  connectWebSocket()
  void loadSessions()
  chatInputRef.value?.focus()
})

onUnmounted(() => {
  dispose()
})
</script>

<style scoped>
.chat-workspace {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: var(--space-5);
  padding: var(--space-5);
}

.chat-panel {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid rgba(203, 213, 225, 0.9);
  border-radius: var(--radius-2xl);
  background: rgba(248, 250, 252, 0.82);
  box-shadow: var(--shadow-soft);
  overflow: hidden;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-5) var(--space-6);
  background: rgba(255, 255, 255, 0.76);
  border-bottom: 1px solid var(--border);
  backdrop-filter: blur(18px);
}

.panel-kicker {
  margin: 0 0 4px;
  color: var(--accent);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.panel-header h2 {
  max-width: min(620px, 70vw);
  margin: 0;
  overflow: hidden;
  color: var(--text-strong);
  font-size: 22px;
  letter-spacing: -0.04em;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.connection-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 7px 11px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: #fff;
  color: var(--text-tertiary);
  font-size: 12px;
  font-weight: 700;
}

.connection-pill span {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: #f59e0b;
}

.connection-pill.connected {
  color: #047857;
}

.connection-pill.connected span {
  background: #10b981;
}

.global-error {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 10px var(--space-6);
  border-bottom: 1px solid #fecdd3;
  background: #fff1f2;
  color: #be123c;
  font-size: 13px;
}

.global-error span {
  flex: 1;
}

.global-error button {
  border: 0;
  background: transparent;
  color: #be123c;
  cursor: pointer;
  font-weight: 700;
}

.usage-panel {
  position: fixed;
  top: var(--space-5);
  right: var(--space-5);
  bottom: var(--space-5);
  z-index: 45;
  width: min(420px, calc(100vw - var(--space-10)));
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-5);
  border: 1px solid rgba(191, 219, 254, 0.9);
  border-radius: var(--radius-2xl);
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 28px 80px rgba(15, 23, 42, 0.22);
  overflow: auto;
}

.usage-panel header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
}

.usage-panel header p {
  margin: 0 0 4px;
  color: #2563eb;
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.usage-panel h3 {
  margin: 0;
  color: var(--text-strong);
  font-size: 20px;
  line-height: 1.25;
  letter-spacing: -0.04em;
}

.usage-panel header button {
  border: 1px solid var(--border);
  border-radius: 999px;
  background: #fff;
  color: var(--text-secondary);
  padding: 6px 10px;
  cursor: pointer;
}

.usage-summary {
  display: grid;
  gap: 4px;
}

.usage-summary strong {
  color: var(--text-strong);
  font-size: 28px;
  line-height: 1.1;
  letter-spacing: -0.05em;
}

.usage-summary span,
.usage-note {
  color: var(--text-secondary);
  font-size: 13px;
}

.usage-progress {
  height: 7px;
  overflow: hidden;
  border-radius: 999px;
  background: #dbeafe;
}

.usage-progress span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #2563eb, #7c3aed);
}

.usage-meta {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
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
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
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
  line-height: 1.4;
}

.breakdown-row > span {
  color: #1d4ed8;
  font-size: 13px;
  font-weight: 900;
  white-space: nowrap;
}

.usage-note {
  margin: 0;
  padding: 10px 12px;
  border-radius: var(--radius-lg);
  background: #eff6ff;
  color: #1d4ed8;
}

.pruning-section {
  display: grid;
  gap: 8px;
}

.pruning-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.pruning-heading h4 {
  margin: 0;
  color: var(--text-strong);
  font-size: 14px;
}

.pruning-heading span {
  color: #c2410c;
  font-size: 12px;
  font-weight: 800;
}

.pruning-list {
  display: grid;
  gap: 8px;
  max-height: 260px;
  overflow-y: auto;
  padding-right: 4px;
  scrollbar-width: thin;
}

.pruning-card {
  display: grid;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid #fed7aa;
  border-radius: var(--radius-lg);
  background: #fff7ed;
}

.pruning-card > div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.pruning-card strong {
  color: #9a3412;
  font-size: 13px;
}

.pruning-card code {
  color: #c2410c;
  font-family: var(--font-mono);
  font-size: 11px;
}

.pruning-card dl {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
  margin: 0;
}

.pruning-card span {
  color: #9a3412;
  font-size: 11px;
}

@media (max-width: 820px) {
  .chat-workspace {
    grid-template-columns: 1fr;
    padding: var(--space-3);
    gap: var(--space-3);
  }

  .panel-header {
    align-items: flex-start;
    padding: var(--space-4);
  }

  .usage-panel {
    inset: var(--space-3) var(--space-3) var(--space-3) auto;
    width: min(380px, calc(100vw - var(--space-6)));
    box-shadow: 0 28px 80px rgba(15, 23, 42, 0.28);
  }
}

.modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: grid;
  place-items: center;
  padding: var(--space-4);
  background: rgba(15, 23, 42, 0.42);
  backdrop-filter: blur(12px);
}

.delete-modal {
  width: min(440px, 100%);
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr);
  gap: var(--space-4);
  padding: var(--space-5);
  border: 1px solid rgba(254, 202, 202, 0.9);
  border-radius: var(--radius-2xl);
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 28px 80px rgba(15, 23, 42, 0.28);
}

.delete-icon {
  width: 44px;
  height: 44px;
  display: grid;
  place-items: center;
  border-radius: 16px;
  background: linear-gradient(135deg, #fee2e2, #fecaca);
  color: #b91c1c;
  font-weight: 900;
  font-size: 16px;
}

.delete-copy {
  min-width: 0;
}

.modal-kicker {
  margin: 0 0 4px;
  color: #e11d48;
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.delete-copy h3 {
  margin: 0 0 10px;
  color: var(--text-strong);
  font-size: 22px;
  line-height: 1.3;
  letter-spacing: -0.04em;
  word-break: break-word;
}

.delete-session-name {
  max-width: 100%;
  margin: 0 0 10px;
  padding: 8px 10px;
  overflow: hidden;
  border: 1px solid #fecdd3;
  border-radius: var(--radius-md);
  background: #fff1f2;
  color: #9f1239;
  font-size: 14px;
  font-weight: 700;
  line-height: 1.45;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.delete-description {
  margin: 0;
  color: var(--text-secondary);
  font-size: 14px;
  line-height: 1.65;
}

.permission-note {
  margin: 12px 0 0;
  color: var(--text-tertiary);
  font-size: 12px;
  line-height: 1.6;
}

.permission-modal .delete-icon {
  background: linear-gradient(135deg, #dbeafe, #bfdbfe);
  color: #1d4ed8;
}

.permission-actions {
  flex-wrap: wrap;
}

.permission-arguments {
  margin: 12px 0 0;
  padding: 10px 12px;
  border-radius: var(--radius-md);
  background: #0f172a;
  color: #dbeafe;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.modal-actions {
  grid-column: 1 / -1;
  display: flex;
  justify-content: flex-end;
  gap: var(--space-3);
  padding-top: var(--space-2);
}

.secondary-action,
.danger-action {
  border-radius: var(--radius-md);
  padding: 10px 16px;
  font-weight: 800;
  font-size: 14px;
  cursor: pointer;
}

.secondary-action {
  border: 1px solid var(--border-strong);
  background: #fff;
  color: var(--text-primary);
}

.secondary-action:hover {
  background: var(--surface-muted);
}

.danger-action {
  border: 1px solid #dc2626;
  background: linear-gradient(135deg, #dc2626, #b91c1c);
  color: #fff;
  box-shadow: 0 12px 26px rgba(220, 38, 38, 0.22);
}

.danger-action:hover {
  transform: translateY(-1px);
}
</style>
