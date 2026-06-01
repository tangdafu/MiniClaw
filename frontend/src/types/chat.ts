export interface ToolCall {
  name: string
  arguments: string
}

export interface ToolPair {
  call: ToolCall
  result: string
}

export interface Message {
  role: 'user' | 'assistant'
  content: string
  reasoning?: string
  toolPairs?: ToolPair[]
  isError?: boolean
}

export interface SessionSummary {
  session_id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

export interface MessagePage {
  items: Message[]
  next_before: number | null
  has_more: boolean
  total: number
}

export interface StreamEvent {
  type: 'text' | 'reasoning' | 'tool_call' | 'tool_result' | 'done' | 'error' | 'session_created'
  content?: string
  name?: string
  arguments?: string
  result?: string
  error?: string
  message?: string
  session_id?: string
}
