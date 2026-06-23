import { type Ref } from 'vue'
import type { PermissionDecision, StreamEvent } from '../types/chat'
import type { SessionRuntimeState } from './useSessionRuntimeState'

interface MessageListLike {
  scrollToBottom: () => void
}

export function useChatTransport(options: {
  sessionId: Ref<string>
  globalError: Ref<string>
  inputText: Ref<string>
  isConnected: Ref<boolean>
  permissionRequestBusy: Ref<boolean>
  messageListRef: Ref<MessageListLike | undefined>
  ensureSessionState: (id: string) => SessionRuntimeState
  ensureAssistantForRun: (state: SessionRuntimeState, runId?: string, status?: 'queued' | 'running' | 'cancelling' | 'cancelled' | 'done' | 'error') => any
  clearPendingPermissionRequestsForRun: (state: SessionRuntimeState, runId: string | undefined, onCleared?: () => void) => void
  clearPendingToolCallsForRun: (state: SessionRuntimeState, runId?: string) => void
  upsertPruningEvent: (state: SessionRuntimeState, event: any) => void
  markQueuedMessagesCancelled: (state: SessionRuntimeState, content: string) => void
  createOptimisticUserMessage: (content: string) => any
  loadRunSummary: (id: string, runId: string) => Promise<void>
  loadSessions: () => Promise<void>
}) {
  const {
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
  } = options

  let ws: WebSocket | null = null
  let shouldReconnect = true

  function scrollIfActive(id: string) {
    if (id === sessionId.value) {
      messageListRef.value?.scrollToBottom()
    }
  }

  function handleEvent(event: StreamEvent) {
    const eventSessionId = event.session_id || sessionId.value
    if (!eventSessionId) return
    const state = ensureSessionState(eventSessionId)

    switch (event.type) {
      case 'queued':
        state.queuedCount = event.queued_count ?? state.queuedCount
        ensureAssistantForRun(state, event.run_id, 'queued')
        scrollIfActive(eventSessionId)
        break

      case 'run_started': {
        const message = ensureAssistantForRun(state, event.run_id, 'running')
        message.status = 'running'
        state.activeRunId = event.run_id ?? ''
        state.isProcessing = true
        scrollIfActive(eventSessionId)
        break
      }

      case 'queue_updated':
        state.activeRunId = event.running_run_id ?? ''
        state.queuedCount = event.queued_count ?? 0
        state.isProcessing = Boolean(state.activeRunId)
        break

      case 'text':
        ensureAssistantForRun(state, event.run_id, 'running').content += event.content ?? ''
        scrollIfActive(eventSessionId)
        break

      case 'reasoning': {
        const message = ensureAssistantForRun(state, event.run_id, 'running')
        message.reasoning = `${message.reasoning ?? ''}${event.content ?? ''}`
        scrollIfActive(eventSessionId)
        break
      }

      case 'context_compression': {
        const message = ensureAssistantForRun(state, event.run_id, 'running')
        message.compressionEvents = message.compressionEvents ?? []
        message.compressionEvents.push({
          stage: event.stage ?? '',
          reason: event.reason,
          detail: event.detail,
          estimated_tokens: event.estimated_tokens,
          trigger_tokens: event.trigger_tokens,
          target_tokens: event.target_tokens,
          head_messages: event.head_messages,
          tail_messages: event.tail_messages,
          covered_messages: event.covered_messages,
          summary_tokens: event.summary_tokens,
          estimated_tokens_after: event.estimated_tokens_after,
        })
        scrollIfActive(eventSessionId)
        break
      }

      case 'context_usage':
        state.contextUsage = {
          stage: event.stage ?? '',
          reason: event.reason,
          estimated_tokens: event.estimated_tokens,
          trigger_tokens: event.trigger_tokens,
          target_tokens: event.target_tokens,
          model_messages: event.model_messages,
          history_messages: event.history_messages,
          compacted: event.compacted,
          cache_hit: event.cache_hit,
          covered_messages: event.covered_messages,
          summary_tokens: event.summary_tokens,
          system_tokens: event.system_tokens,
          summary_tokens_breakdown: event.summary_tokens_breakdown,
          user_tokens: event.user_tokens,
          assistant_tokens: event.assistant_tokens,
          tool_tokens: event.tool_tokens,
        }
        break

      case 'context_pruning':
        upsertPruningEvent(state, {
          stage: event.stage ?? '',
          reason: event.reason,
          prune_id: event.prune_id,
          tool_name: event.tool_name,
          tool_call_id: event.tool_call_id,
          original_tokens: event.original_tokens,
          retained_tokens: event.retained_tokens,
          omitted_tokens: event.omitted_tokens,
          message_index: event.message_index,
        })
        break

      case 'tool_call':
        if (!event.tool_call_id) return
        state.pendingToolCalls[event.tool_call_id] = {
          name: event.name ?? '',
          arguments: event.arguments ?? '',
          toolCallId: event.tool_call_id,
          runId: event.run_id,
          status: 'running',
        }
        scrollIfActive(eventSessionId)
        break

      case 'tool_permission_request':
        if (!event.request_id) return
        state.pendingPermissionRequests[event.request_id] = {
          request_id: event.request_id,
          session_id: event.session_id,
          run_id: event.run_id,
          tool_call_id: event.tool_call_id,
          tool_name: event.tool_name || event.name || '',
          arguments: event.arguments ?? '',
          category: event.category,
          risk_level: event.risk_level,
          reason: event.reason,
          policy: event.policy,
          created_at: event.created_at,
        }
        if (event.run_id) {
          ensureAssistantForRun(state, event.run_id, 'running')
        }
        scrollIfActive(eventSessionId)
        break

      case 'tool_permission_decision':
        if (event.request_id) {
          delete state.pendingPermissionRequests[event.request_id]
        }
        permissionRequestBusy.value = false
        if (event.resolved === false) {
          globalError.value = '权限请求响应失败，可能该请求已失效。'
        }
        break

      case 'tool_result':
        if (event.tool_call_id && state.pendingToolCalls[event.tool_call_id]) {
          const pending = state.pendingToolCalls[event.tool_call_id]
          const message = ensureAssistantForRun(state, event.run_id, 'running')
          message.toolPairs = message.toolPairs ?? []
          message.toolPairs.push({
            call: {
              ...pending,
              status: event.decision === 'allow' ? 'completed' : 'blocked',
              decision: event.decision,
              blockedReason: event.blocked_reason,
              startedAt: event.started_at,
              finishedAt: event.finished_at,
              changedFiles: event.changed_files ?? [],
            },
            result: event.result ?? '',
          })
          delete state.pendingToolCalls[event.tool_call_id]
          scrollIfActive(eventSessionId)
        }
        break

      case 'cancel_requested': {
        const message = ensureAssistantForRun(state, event.run_id, 'cancelling')
        message.status = event.cancelled ? 'cancelling' : message.status
        scrollIfActive(eventSessionId)
        break
      }

      case 'done': {
        const message = ensureAssistantForRun(state, event.run_id, 'done')
        message.status = 'done'
        clearPendingToolCallsForRun(state, event.run_id)
        clearPendingPermissionRequestsForRun(state, event.run_id, () => {
          permissionRequestBusy.value = false
        })
        if (state.activeRunId === (event.run_id ?? '')) {
          state.activeRunId = ''
          state.isProcessing = false
        }
        if (event.run_id) {
          void loadRunSummary(eventSessionId, event.run_id)
        }
        void loadSessions()
        break
      }

      case 'cancelled': {
        const message = ensureAssistantForRun(state, event.run_id, 'cancelled')
        message.status = 'cancelled'
        if (!message.content) message.content = '[已停止生成]'
        clearPendingToolCallsForRun(state, event.run_id)
        clearPendingPermissionRequestsForRun(state, event.run_id, () => {
          permissionRequestBusy.value = false
        })
        if (state.activeRunId === (event.run_id ?? '')) {
          state.activeRunId = ''
          state.isProcessing = false
        }
        if (event.run_id) {
          void loadRunSummary(eventSessionId, event.run_id)
        }
        scrollIfActive(eventSessionId)
        break
      }

      case 'queue_cleared':
        state.queuedCount = 0
        markQueuedMessagesCancelled(state, '[已从队列移除]')
        break

      case 'session_stopped':
        state.queuedCount = 0
        state.isProcessing = false
        state.activeRunId = ''
        state.pendingPermissionRequests = {}
        permissionRequestBusy.value = false
        markQueuedMessagesCancelled(state, '[已停止]')
        break

      case 'error': {
        state.messages.push({
          role: 'assistant',
          content: event.error || event.message || '未知错误',
          isError: true,
          runId: event.run_id,
          status: 'error',
          clientKey: `error:${event.run_id || 'unknown'}:${Date.now()}`,
        })
        if (event.run_id) {
          void loadRunSummary(eventSessionId, event.run_id)
        }
        scrollIfActive(eventSessionId)
        void loadSessions()
        break
      }
    }
  }

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
          ensureSessionState(data.session_id)
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

  function sendMessage() {
    const text = inputText.value.trim()
    if (!text || !ws || ws.readyState !== WebSocket.OPEN || !sessionId.value) return

    const state = ensureSessionState(sessionId.value)
    globalError.value = ''
    state.messages.push(createOptimisticUserMessage(text))
    inputText.value = ''
    messageListRef.value?.scrollToBottom()

    ws.send(JSON.stringify({
      type: 'chat',
      session_id: sessionId.value,
      message: text,
    }))
  }

  function sendControl(type: 'cancel_current' | 'clear_queue' | 'stop_session') {
    if (!ws || ws.readyState !== WebSocket.OPEN || !sessionId.value) return
    ws.send(JSON.stringify({ type, session_id: sessionId.value }))
  }

  function resolveToolPermission(requestId: string, decision: PermissionDecision) {
    if (!ws || ws.readyState !== WebSocket.OPEN || !sessionId.value || permissionRequestBusy.value) return
    permissionRequestBusy.value = true
    ws.send(JSON.stringify({
      type: 'respond_tool_permission',
      session_id: sessionId.value,
      request_id: requestId,
      decision,
    }))
  }

  function dispose() {
    shouldReconnect = false
    if (ws) {
      ws.close()
    }
  }

  return {
    connectWebSocket,
    sendMessage,
    sendControl,
    resolveToolPermission,
    dispose,
  }
}
