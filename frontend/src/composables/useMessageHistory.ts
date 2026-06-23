import { computed, nextTick, ref, type Ref } from 'vue'
import type { ContextPruningEvent, ContextUsageEvent, Message, MessagePage, RunSummary } from '../types/chat'
import type { SessionRuntimeState } from './useSessionRuntimeState'

export function useMessageHistory(options: {
  sessionId: Ref<string>
  globalError: Ref<string>
  messageListRef: Ref<{ getScrollHeight: () => number; restoreScrollAfterPrepend: (previousHeight: number) => void; scrollToBottom: () => void } | undefined>
  ensureSessionState: (id: string) => SessionRuntimeState
  normalizeMessage: (message: Message, fallbackKey: string) => Message
  fetchJson: <T>(url: string, init?: RequestInit) => Promise<T>
  loadContextUsage: (id: string) => Promise<void>
}) {
  const {
    sessionId,
    globalError,
    messageListRef,
    ensureSessionState,
    normalizeMessage,
    fetchJson,
    loadContextUsage,
  } = options

  async function fetchMessagePage(id: string, before?: number): Promise<MessagePage> {
    const params = new URLSearchParams({ limit: '20' })
    if (before !== undefined) params.set('before', String(before))
    return await fetchJson<MessagePage>(`/sessions/${encodeURIComponent(id)}/messages?${params}`)
  }

  async function loadRunSummary(id: string, runId: string) {
    const state = ensureSessionState(id)
    const message = state.messages.find((item) => item.role === 'assistant' && item.runId === runId)
    if (!message) return
    try {
      const summary = await fetchJson<RunSummary>(`/sessions/${encodeURIComponent(id)}/runs/${encodeURIComponent(runId)}`)
      message.runSummary = summary
      if (!message.status && summary.status) {
        message.status = summary.status as Message['status']
      }
    } catch {
      // Ignore missing or not-yet-persisted run summaries.
    }
  }

  async function loadLatestMessages(id: string) {
    const state = ensureSessionState(id)
    state.isLoadingHistory = true
    try {
      const page = await fetchMessagePage(id)
      if (!state.isProcessing && state.queuedCount === 0) {
        state.messages = page.items.map((message, index) => normalizeMessage(message, `history:${id}:${index}`))
        for (const message of state.messages) {
          if (message.role === 'assistant' && message.runId && !message.runSummary) {
            void loadRunSummary(id, message.runId)
          }
        }
      }
      state.nextBefore = page.next_before
      state.hasMore = page.has_more
      state.hasLoadedHistory = true
      await loadContextUsage(id)
      messageListRef.value?.scrollToBottom()
    } catch (error) {
      globalError.value = error instanceof Error ? error.message : '加载消息失败'
    } finally {
      state.isLoadingHistory = false
    }
  }

  async function loadOlderMessages() {
    if (!sessionId.value) return
    const state = ensureSessionState(sessionId.value)
    if (!state.hasMore || state.nextBefore === null || state.isLoadingHistory) return

    const previousHeight = messageListRef.value?.getScrollHeight() ?? 0
    state.isLoadingHistory = true

    try {
      const page = await fetchMessagePage(sessionId.value, state.nextBefore)
      state.messages = [
        ...page.items.map((message, index) => normalizeMessage(message, `history:${sessionId.value}:${state.nextBefore}:${index}`)),
        ...state.messages,
      ]
      state.nextBefore = page.next_before
      state.hasMore = page.has_more
      await nextTick()
      messageListRef.value?.restoreScrollAfterPrepend(previousHeight)
    } catch (error) {
      globalError.value = error instanceof Error ? error.message : '加载更早消息失败'
    } finally {
      state.isLoadingHistory = false
    }
  }

  return {
    fetchMessagePage,
    loadRunSummary,
    loadLatestMessages,
    loadOlderMessages,
  }
}

export function useContextUsagePanel(options: {
  activeRuntime: Ref<SessionRuntimeState>
  ensureSessionState: (id: string) => SessionRuntimeState
  fetchJson: <T>(url: string, init?: RequestInit) => Promise<T>
}) {
  const { activeRuntime, ensureSessionState, fetchJson } = options
  const usagePanelOpen = ref(false)

  async function loadContextUsage(id: string) {
    const state = ensureSessionState(id)
    try {
      const usage = await fetchJson<ContextUsageEvent>(`/sessions/${encodeURIComponent(id)}/context-usage`)
      state.contextUsage = usage
      state.pruningEvents = []
      for (const event of usage.pruning_records ?? []) {
        upsertPruningEvent(state, event)
      }
    } catch {
      state.contextUsage = undefined
      state.pruningEvents = []
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

  const activeContextUsage = computed(() => activeRuntime.value.contextUsage)
  const activePruningEvents = computed(() => activeRuntime.value.pruningEvents)
  const usagePercent = computed(() => {
    const used = activeContextUsage.value?.estimated_tokens ?? 0
    const total = activeContextUsage.value?.trigger_tokens ?? 0
    if (total <= 0) return 0
    return Math.min(100, Math.round((used / total) * 100))
  })
  const usageBreakdownRows = computed(() => {
    const usage = activeContextUsage.value
    return [
      { label: '系统提示词', description: '动态 system prompt', value: usage?.system_tokens },
      { label: '摘要', description: 'model_context.json 压缩摘要', value: usage?.summary_tokens_breakdown ?? usage?.summary_tokens },
      { label: '用户输入', description: 'role=user 的消息', value: usage?.user_tokens },
      { label: 'Assistant', description: 'assistant 回复和 tool_calls', value: usage?.assistant_tokens },
      { label: '工具返回', description: 'role=tool 的工具结果', value: usage?.tool_tokens },
    ]
  })

  return {
    usagePanelOpen,
    loadContextUsage,
    activeContextUsage,
    activePruningEvents,
    usagePercent,
    usageBreakdownRows,
  }
}
