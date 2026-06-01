<template>
  <div class="chat-workspace">
    <SessionSidebar
      :sessions="sessions"
      :active-session-id="sessionId"
      :disabled="isProcessing"
      :is-loading="isLoadingSessions"
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
        :messages="messages"
        :is-loading-history="isLoadingHistory"
        :has-more="hasMore"
        :is-generating="isProcessing"
        @load-older="loadOlderMessages"
      />

      <ChatInput
        ref="chatInputRef"
        v-model="inputText"
        :disabled="isProcessing || !isConnected || !sessionId"
        :is-processing="isProcessing"
        placeholder="向 MiniClaw 提问，或描述你想完成的任务..."
        @send="sendMessage"
      />
    </section>

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
import type { Message, MessagePage, SessionSummary, StreamEvent, ToolCall } from '../types/chat'

const messages = ref<Message[]>([])
const sessions = ref<SessionSummary[]>([])
const inputText = ref('')
const isProcessing = ref(false)
const isConnected = ref(false)
const isLoadingSessions = ref(false)
const isLoadingHistory = ref(false)
const hasMore = ref(false)
const nextBefore = ref<number | null>(null)
const globalError = ref('')
const sessionId = ref('')
const messageListRef = ref<InstanceType<typeof MessageList>>()
const chatInputRef = ref<InstanceType<typeof ChatInput>>()
const deleteTarget = ref<SessionSummary | null>(null)

let ws: WebSocket | null = null
let pendingToolCall: ToolCall | null = null
let shouldReconnect = true

const activeTitle = computed(() => {
  return sessions.value.find((session) => session.session_id === sessionId.value)?.title || '新会话'
})

function connectWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsUrl = `${protocol}//${window.location.host}/ws/chat`

  ws = new WebSocket(wsUrl)

  ws.onopen = () => {
    isConnected.value = true
    globalError.value = ''
  }

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data) as StreamEvent
      if (data.type === 'session_created' && data.session_id) {
        sessionId.value = data.session_id
        void loadSessions()
        return
      }
      handleEvent(data)
    } catch {
      // Ignore malformed stream events.
    }
  }

  ws.onclose = () => {
    isConnected.value = false
    if (shouldReconnect) {
      globalError.value = '连接已断开，正在重连...'
      setTimeout(connectWebSocket, 3000)
    }
  }

  ws.onerror = () => {
    isConnected.value = false
    globalError.value = '连接失败，请确认后端服务正在运行。'
  }
}

async function loadSessions() {
  isLoadingSessions.value = true
  try {
    const data = await fetchJson<{ sessions: SessionSummary[] }>('/sessions')
    sessions.value = data.sessions

    if (!sessionId.value && sessions.value.length > 0) {
      await selectSession(sessions.value[0].session_id)
    } else if (!sessionId.value) {
      await createNewSession()
    }
  } catch (error) {
    globalError.value = error instanceof Error ? error.message : '加载会话失败'
  } finally {
    isLoadingSessions.value = false
  }
}

async function createNewSession() {
  if (isProcessing.value) return

  try {
    const data = await fetchJson<{ session_id: string }>('/sessions', { method: 'POST' })
    sessionId.value = data.session_id
    messages.value = []
    pendingToolCall = null
    nextBefore.value = null
    hasMore.value = false
    await loadSessions()
    await nextTick()
    chatInputRef.value?.focus()
  } catch (error) {
    globalError.value = error instanceof Error ? error.message : '创建会话失败'
  }
}

async function deleteSession(id: string) {
  if (isProcessing.value) return

  const target = sessions.value.find((session) => session.session_id === id)
  if (!target) return
  deleteTarget.value = target
}

function cancelDelete() {
  deleteTarget.value = null
}

async function confirmDeleteSession() {
  if (isProcessing.value || !deleteTarget.value) return

  const id = deleteTarget.value.session_id
  deleteTarget.value = null

  try {
    await fetchJson<{ deleted: boolean; session_id: string }>(`/sessions/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    })

    const wasActive = id === sessionId.value
    const remainingSessions = sessions.value.filter((session) => session.session_id !== id)
    sessions.value = remainingSessions

    if (!wasActive) {
      await loadSessions()
      return
    }

    messages.value = []
    pendingToolCall = null
    nextBefore.value = null
    hasMore.value = false
    sessionId.value = ''

    if (remainingSessions.length > 0) {
      await selectSession(remainingSessions[0].session_id)
      await loadSessions()
    } else {
      await createNewSession()
    }
  } catch (error) {
    globalError.value = error instanceof Error ? error.message : '删除会话失败'
  }
}

async function selectSession(id: string) {
  if (isProcessing.value || id === sessionId.value) return

  sessionId.value = id
  pendingToolCall = null
  await loadLatestMessages(id)
}

async function loadLatestMessages(id: string) {
  isLoadingHistory.value = true
  try {
    const page = await fetchMessagePage(id)
    messages.value = page.items.map(normalizeMessage)
    nextBefore.value = page.next_before
    hasMore.value = page.has_more
    messageListRef.value?.scrollToBottom()
  } catch (error) {
    globalError.value = error instanceof Error ? error.message : '加载消息失败'
  } finally {
    isLoadingHistory.value = false
  }
}

async function loadOlderMessages() {
  if (!sessionId.value || !hasMore.value || nextBefore.value === null || isLoadingHistory.value) return

  const previousHeight = messageListRef.value?.getScrollHeight() ?? 0
  isLoadingHistory.value = true

  try {
    const page = await fetchMessagePage(sessionId.value, nextBefore.value)
    messages.value = [...page.items.map(normalizeMessage), ...messages.value]
    nextBefore.value = page.next_before
    hasMore.value = page.has_more
    await nextTick()
    messageListRef.value?.restoreScrollAfterPrepend(previousHeight)
  } catch (error) {
    globalError.value = error instanceof Error ? error.message : '加载更早消息失败'
  } finally {
    isLoadingHistory.value = false
  }
}

async function fetchMessagePage(id: string, before?: number): Promise<MessagePage> {
  const params = new URLSearchParams({ limit: '20' })
  if (before !== undefined) params.set('before', String(before))
  return await fetchJson<MessagePage>(`/sessions/${encodeURIComponent(id)}/messages?${params}`)
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  const contentType = response.headers.get('content-type') ?? ''

  if (!response.ok) {
    throw new Error(`请求失败：${response.status} ${url}`)
  }

  if (!contentType.includes('application/json')) {
    throw new Error(`接口没有返回 JSON：${url}`)
  }

  return await response.json() as T
}

function normalizeMessage(message: Message): Message {
  return {
    ...message,
    toolPairs: message.toolPairs ?? [],
  }
}

function sendMessage() {
  const text = inputText.value.trim()
  if (!text || isProcessing.value || !ws || ws.readyState !== WebSocket.OPEN || !sessionId.value) return

  globalError.value = ''
  messages.value.push({ role: 'user', content: text })
  inputText.value = ''
  isProcessing.value = true
  messageListRef.value?.scrollToBottom()

  messages.value.push({ role: 'assistant', content: '' })

  ws.send(JSON.stringify({
    session_id: sessionId.value,
    message: text,
  }))
}

function handleEvent(event: StreamEvent) {
  const lastMsg = messages.value[messages.value.length - 1]
  if (!lastMsg || lastMsg.role !== 'assistant' || lastMsg.isError) return

  switch (event.type) {
    case 'text':
      lastMsg.content += event.content ?? ''
      messageListRef.value?.scrollToBottom()
      break

    case 'reasoning':
      lastMsg.reasoning = `${lastMsg.reasoning ?? ''}${event.content ?? ''}`
      messageListRef.value?.scrollToBottom()
      break

    case 'tool_call':
      pendingToolCall = {
        name: event.name ?? '',
        arguments: event.arguments ?? '',
      }
      messageListRef.value?.scrollToBottom()
      break

    case 'tool_result':
      if (pendingToolCall) {
        lastMsg.toolPairs = lastMsg.toolPairs ?? []
        lastMsg.toolPairs.push({
          call: pendingToolCall,
          result: event.result ?? '',
        })
        pendingToolCall = null
        messageListRef.value?.scrollToBottom()
      }
      break

    case 'done':
      pendingToolCall = null
      isProcessing.value = false
      void loadSessions()
      break

    case 'error':
      messages.value.push({
        role: 'assistant',
        content: event.error || event.message || '未知错误',
        isError: true,
      })
      pendingToolCall = null
      isProcessing.value = false
      messageListRef.value?.scrollToBottom()
      void loadSessions()
      break
  }
}

onMounted(() => {
  connectWebSocket()
  void loadSessions()
  chatInputRef.value?.focus()
})

onUnmounted(() => {
  shouldReconnect = false
  if (ws) {
    ws.close()
  }
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
