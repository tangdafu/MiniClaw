import { computed, ref, type Ref } from 'vue'
import type { ContextPruningEvent, ContextUsageEvent, Message, ToolCall, ToolPermissionRequest } from '../types/chat'

export interface SessionRuntimeState {
  messages: Message[]
  isProcessing: boolean
  pendingToolCalls: Record<string, ToolCall>
  pendingPermissionRequests: Record<string, ToolPermissionRequest>
  activeRunId: string
  queuedCount: number
  contextUsage?: ContextUsageEvent
  pruningEvents: ContextPruningEvent[]
  nextBefore: number | null
  hasMore: boolean
  isLoadingHistory: boolean
  hasLoadedHistory: boolean
}

function createLocalKey(prefix: string): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `${prefix}:${crypto.randomUUID()}`
  }
  return `${prefix}:${Date.now()}:${Math.random().toString(16).slice(2)}`
}

export function createRuntimeState(): SessionRuntimeState {
  return {
    messages: [],
    isProcessing: false,
    pendingToolCalls: {},
    pendingPermissionRequests: {},
    activeRunId: '',
    queuedCount: 0,
    contextUsage: undefined,
    pruningEvents: [],
    nextBefore: null,
    hasMore: false,
    isLoadingHistory: false,
    hasLoadedHistory: false,
  }
}

export function normalizeMessage(message: Message, fallbackKey: string): Message {
  return {
    ...message,
    clientKey: message.clientKey ?? fallbackKey,
    toolPairs: message.toolPairs ?? [],
    runSummary: message.runSummary,
  }
}

export function createOptimisticUserMessage(content: string): Message {
  return {
    role: 'user',
    content,
    clientKey: createLocalKey('user'),
  }
}

export function useSessionRuntimeState(sessionId: Ref<string>) {
  const sessionStates = ref<Record<string, SessionRuntimeState>>({})
  const emptyRuntime = createRuntimeState()

  function ensureSessionState(id: string): SessionRuntimeState {
    if (!sessionStates.value[id]) {
      sessionStates.value[id] = createRuntimeState()
    }
    return sessionStates.value[id]
  }

  const activeRuntime = computed(() => sessionId.value ? ensureSessionState(sessionId.value) : emptyRuntime)
  const activeMessages = computed(() => activeRuntime.value.messages)
  const activeContextUsage = computed(() => activeRuntime.value.contextUsage)
  const activePruningEvents = computed(() => activeRuntime.value.pruningEvents)
  const activePermissionRequest = computed(() => {
    const requests = Object.values(activeRuntime.value.pendingPermissionRequests)
    return requests.length ? requests[0] : null
  })
  const runningSessionIds = computed(() => Object.entries(sessionStates.value)
    .filter(([, state]) => state.isProcessing)
    .map(([id]) => id))
  const queuedCounts = computed(() => Object.fromEntries(
    Object.entries(sessionStates.value).map(([id, state]) => [id, state.queuedCount]),
  ))

  function ensureAssistantForRun(state: SessionRuntimeState, runId?: string, status: Message['status'] = 'running'): Message {
    const normalizedRunId = runId || state.activeRunId || 'unknown'
    let message = state.messages.find((item) => item.role === 'assistant' && item.runId === normalizedRunId)
    if (!message) {
      message = {
        role: 'assistant',
        content: '',
        toolPairs: [],
        runId: normalizedRunId,
        status,
        clientKey: createLocalKey(`assistant:${normalizedRunId}`),
      }
      state.messages.push(message)
    }
    if (message.status !== 'done' && message.status !== 'cancelled' && message.status !== 'error') {
      message.status = status
    }
    return message
  }

  function clearPendingPermissionRequestsForRun(
    state: SessionRuntimeState,
    runId: string | undefined,
    onCleared?: () => void,
  ) {
    if (!runId) return
    for (const requestId of Object.keys(state.pendingPermissionRequests)) {
      if (state.pendingPermissionRequests[requestId]?.run_id === runId) {
        delete state.pendingPermissionRequests[requestId]
      }
    }
    onCleared?.()
  }

  function clearPendingToolCallsForRun(state: SessionRuntimeState, runId?: string) {
    if (!runId) return
    for (const [toolCallId, call] of Object.entries(state.pendingToolCalls)) {
      if (call.runId === runId) {
        delete state.pendingToolCalls[toolCallId]
      }
    }
  }

  function pruningEventKey(event: ContextPruningEvent) {
    return event.prune_id || `${event.tool_call_id || 'tool'}-${event.message_index ?? 'unknown'}`
  }

  function upsertPruningEvent(state: SessionRuntimeState, event: ContextPruningEvent) {
    const key = pruningEventKey(event)
    const existingIndex = state.pruningEvents.findIndex((item) => pruningEventKey(item) === key)
    if (existingIndex >= 0) {
      state.pruningEvents.splice(existingIndex, 1, event)
      return
    }
    state.pruningEvents.push(event)
  }

  function markQueuedMessagesCancelled(state: SessionRuntimeState, content: string) {
    for (const message of state.messages) {
      if (message.role === 'assistant' && message.status === 'queued') {
        message.status = 'cancelled'
        message.content = content
      }
    }
    for (const toolCallId of Object.keys(state.pendingToolCalls)) {
      delete state.pendingToolCalls[toolCallId]
    }
  }

  return {
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
  }
}
