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
  compressionEvents?: CompressionEvent[]
  isError?: boolean
  runId?: string
  status?: 'queued' | 'running' | 'cancelled' | 'done' | 'error'
}

export interface CompressionEvent {
  stage: string
  reason?: string
  detail?: string
  estimated_tokens?: number
  trigger_tokens?: number
  target_tokens?: number
  head_messages?: number
  tail_messages?: number
  covered_messages?: number
  summary_tokens?: number
  estimated_tokens_after?: number
}

export interface ContextUsageEvent {
  stage: string
  reason?: string
  estimated_tokens?: number
  trigger_tokens?: number
  target_tokens?: number
  model_messages?: number
  history_messages?: number
  compacted?: boolean
  cache_hit?: boolean
  covered_messages?: number
  summary_tokens?: number
  system_tokens?: number
  summary_tokens_breakdown?: number
  user_tokens?: number
  assistant_tokens?: number
  tool_tokens?: number
  pruning_records?: ContextPruningEvent[]
}

export interface ContextPruningEvent {
  stage: string
  reason?: string
  prune_id?: string
  tool_name?: string
  tool_call_id?: string
  original_tokens?: number
  retained_tokens?: number
  omitted_tokens?: number
  message_index?: number
  pruning_records?: ContextPruningEvent[]
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
  type: 'text' | 'reasoning' | 'tool_call' | 'tool_result' | 'done' | 'error' | 'session_created' | 'context_compression' | 'context_usage' | 'context_pruning' | 'queued' | 'queue_updated' | 'run_started' | 'cancelled' | 'queue_cleared' | 'session_stopped' | 'cancel_requested'
  content?: string
  name?: string
  arguments?: string
  result?: string
  error?: string
  message?: string
  session_id?: string
  run_id?: string
  running_run_id?: string
  queue_position?: number
  queued_count?: number
  cleared_count?: number
  cancelled?: boolean
  stage?: string
  reason?: string
  detail?: string
  estimated_tokens?: number
  trigger_tokens?: number
  target_tokens?: number
  head_messages?: number
  tail_messages?: number
  covered_messages?: number
  summary_tokens?: number
  estimated_tokens_after?: number
  model_messages?: number
  history_messages?: number
  compacted?: boolean
  cache_hit?: boolean
  system_tokens?: number
  summary_tokens_breakdown?: number
  user_tokens?: number
  assistant_tokens?: number
  tool_tokens?: number
  prune_id?: string
  tool_name?: string
  tool_call_id?: string
  original_tokens?: number
  retained_tokens?: number
  omitted_tokens?: number
  message_index?: number
}
