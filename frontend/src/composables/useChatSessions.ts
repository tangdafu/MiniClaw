import { type Ref } from 'vue'
import type { SessionSummary } from '../types/chat'
import type { SessionRuntimeState } from './useSessionRuntimeState'

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

export function useChatSessions(options: {
  sessions: Ref<SessionSummary[]>
  sessionId: Ref<string>
  sessionStates: Ref<Record<string, SessionRuntimeState>>
  isLoadingSessions: Ref<boolean>
  globalError: Ref<string>
  deleteTarget: Ref<SessionSummary | null>
  createRuntimeState: () => SessionRuntimeState
  getLoadContextUsage: () => (id: string) => Promise<void> | void
  getLoadLatestMessages: () => (id: string) => Promise<void>
  focusInput: () => void
}) {
  const {
    sessions,
    sessionId,
    sessionStates,
    isLoadingSessions,
    globalError,
    deleteTarget,
    createRuntimeState,
    getLoadContextUsage,
    getLoadLatestMessages,
    focusInput,
  } = options

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
    try {
      const data = await fetchJson<{ session_id: string }>('/sessions', { method: 'POST' })
      sessionId.value = data.session_id
      sessionStates.value[data.session_id] = createRuntimeState()
      await loadSessions()
      focusInput()
    } catch (error) {
      globalError.value = error instanceof Error ? error.message : '创建会话失败'
    }
  }

  async function selectSession(id: string) {
    if (id === sessionId.value) return

    sessionId.value = id
    const state = sessionStates.value[id] ?? (sessionStates.value[id] = createRuntimeState())
    if (!state.hasLoadedHistory && state.messages.length === 0) {
      await getLoadLatestMessages()(id)
    } else {
      await getLoadContextUsage()(id)
    }
  }

  async function deleteSession(id: string) {
    const state = sessionStates.value[id]
    if (state?.isProcessing || state?.queuedCount) {
      globalError.value = '该会话还有运行中或排队任务，请先停止后再删除。'
      return
    }

    const target = sessions.value.find((session) => session.session_id === id)
    if (!target) return
    deleteTarget.value = target
  }

  function cancelDelete() {
    deleteTarget.value = null
  }

  async function confirmDeleteSession() {
    if (!deleteTarget.value) return

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

      delete sessionStates.value[id]
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

  return {
    loadSessions,
    createNewSession,
    selectSession,
    deleteSession,
    cancelDelete,
    confirmDeleteSession,
    fetchJson,
  }
}
