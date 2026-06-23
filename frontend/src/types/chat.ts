export type PermissionDecision = 'allow_once' | 'deny_once' | 'allow_session' | 'deny_session'

export interface ToolPermissionRequest {
  request_id: string
  session_id?: string
  run_id?: string
  tool_call_id?: string
  tool_name: string
  arguments: string
  category?: string
  risk_level?: 'low' | 'medium' | 'high'
  reason?: string
  policy?: string
  created_at?: string
}

export interface RunSummary {
  run_id: string
  session_id?: string
  status: 'running' | 'done' | 'cancelled' | 'error'
  started_at: string
  finished_at?: string | null
  tool_calls_total: number
  tool_calls_blocked: number
  changed_files: string[]
  summary_text?: string | null
  last_error?: string | null
  commands: Array<{
    command: string
    workdir?: string | null
    decision?: string
  }>
}

export interface ToolCall {
  name: string
  arguments: string
  toolCallId?: string
  runId?: string
  status?: 'pending' | 'running' | 'blocked' | 'completed'
  decision?: 'allow' | 'deny' | 'confirm'
  blockedReason?: string
  startedAt?: string
  finishedAt?: string
  changedFiles?: string[]
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
  status?: 'queued' | 'running' | 'cancelling' | 'cancelled' | 'done' | 'error'
  runSummary?: RunSummary
  clientKey?: string
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
  type: 'text' | 'reasoning' | 'tool_call' | 'tool_result' | 'done' | 'error' | 'session_created' | 'context_compression' | 'context_usage' | 'context_pruning' | 'queued' | 'queue_updated' | 'run_started' | 'cancelled' | 'queue_cleared' | 'session_stopped' | 'cancel_requested' | 'tool_permission_request' | 'tool_permission_decision'
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
  decision?: 'allow' | 'deny' | 'confirm'
  blocked_reason?: string
  changed_files?: string[]
  started_at?: string
  finished_at?: string
  original_tokens?: number
  retained_tokens?: number
  omitted_tokens?: number
  message_index?: number
  request_id?: string
  approved?: boolean
  resolved?: boolean
  permission_decision?: PermissionDecision
  category?: string
  risk_level?: 'low' | 'medium' | 'high'
  policy?: string
  created_at?: string
}
