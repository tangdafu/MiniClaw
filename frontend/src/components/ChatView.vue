<template>
  <div class="chat-container">
    <!-- 全局错误提示 -->
    <div v-if="globalError" class="global-error">
      <span class="error-icon">⚠️</span>
      <span class="error-text">{{ globalError }}</span>
      <button class="error-close" @click="globalError = ''">✕</button>
    </div>

    <div class="messages" ref="messagesRef">
      <div
        v-for="(msg, index) in messages"
        :key="index"
        class="message"
        :class="[msg.role, { error: msg.isError }]"
      >
        <div class="avatar">
          {{ msg.role === 'user' ? '👤' : (msg.isError ? '⚠️' : '🤖') }}
        </div>
        <div class="content">
          <!-- 用户消息 -->
          <div v-if="msg.role === 'user'" class="text">{{ msg.content }}</div>

          <!-- 错误消息 -->
          <div v-else-if="msg.isError" class="text error-text-content">{{ msg.content }}</div>

          <!-- AI 消息 -->
          <template v-else>
            <!-- 1. 思考内容（可折叠） -->
            <div v-if="msg.reasoning" class="reasoning-section">
              <button class="reasoning-toggle" @click="toggleReasoning(index)">
                <span class="toggle-icon">{{ msg.showReasoning ? '▼' : '▶' }}</span>
                <span class="toggle-text">
                  {{ msg.showReasoning ? '隐藏思考过程' : '显示思考过程' }}
                </span>
                <span class="reasoning-badge">{{ msg.reasoning.length }} 字</span>
              </button>
              <div v-show="msg.showReasoning" class="reasoning-content">
                <pre>{{ msg.reasoning }}</pre>
              </div>
            </div>

            <!-- 2. 工具执行和执行结果（成对显示，默认折叠） -->
            <div v-if="msg.toolPairs && msg.toolPairs.length > 0" class="tools-section">
              <button class="tools-toggle" @click="toggleTools(index)">
                <span class="toggle-icon">{{ msg.showTools ? '▼' : '▶' }}</span>
                <span class="toggle-text">
                  {{ msg.showTools ? '隐藏工具执行' : '显示工具执行' }}
                </span>
                <span class="tools-badge">{{ msg.toolPairs.length }} 个工具</span>
              </button>
              <div v-show="msg.showTools" class="tools-content">
                <div v-for="(pair, i) in msg.toolPairs" :key="i" class="tool-pair">
                  <!-- 工具调用 -->
                  <div class="tool-call">
                    <div class="tool-header">
                      <span class="tool-icon">🔧</span>
                      <span class="tool-name">{{ pair.call.name }}</span>
                    </div>
                    <div class="tool-args">{{ pair.call.arguments }}</div>
                  </div>
                  <!-- 工具结果 -->
                  <div class="tool-result">
                    <div class="tool-header">
                      <span class="tool-icon">📤</span>
                      <span class="tool-name">{{ pair.call.name }} 结果</span>
                    </div>
                    <pre class="tool-output">{{ pair.result }}</pre>
                  </div>
                </div>
              </div>
            </div>

            <!-- 3. 返回的具体内容 -->
            <div v-if="msg.content" class="text" v-html="renderMarkdown(msg.content)"></div>
          </template>
        </div>
      </div>

      <div v-if="isLoading" class="message assistant loading">
        <div class="avatar">🤖</div>
        <div class="content">
          <div class="typing-indicator">
            <span></span><span></span><span></span>
          </div>
        </div>
      </div>
    </div>

    <div class="input-area">
      <div class="input-box">
        <textarea
          v-model="inputText"
          @keydown.enter.prevent="handleEnter"
          placeholder="输入消息...（Shift+Enter 换行）"
          rows="1"
          ref="inputRef"
        ></textarea>
        <button 
          @click="sendMessage" 
          :disabled="isProcessing || !inputText.trim() || !isConnected"
          class="send-btn"
        >
          <span v-if="isProcessing" class="spinner"></span>
          <span v-else>{{ isConnected ? '发送' : '连接中...' }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, onMounted, onUnmounted } from 'vue'
import { marked } from 'marked'

interface ToolCall {
  name: string
  arguments: string
}

interface ToolPair {
  call: ToolCall
  result: string
}

interface Message {
  role: 'user' | 'assistant'
  content: string
  reasoning?: string
  showReasoning?: boolean
  toolPairs?: ToolPair[]
  showTools?: boolean
  isError?: boolean
}

const messages = ref<Message[]>([
  {
    role: 'assistant',
    content: '你好！我是 MiniClaw Agent。我可以帮你执行命令、读取 skill 文件等。有什么可以帮你的吗？'
  }
])

const inputText = ref('')
const isLoading = ref(false)
const isProcessing = ref(false)
const isConnected = ref(false)
const globalError = ref('')
const messagesRef = ref<HTMLDivElement>()
const inputRef = ref<HTMLTextAreaElement>()
const sessionId = ref('')  // 当前会话 ID

let ws: WebSocket | null = null

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
      const data = JSON.parse(event.data)
      // 处理 session_created 事件
      if (data.type === 'session_created') {
        sessionId.value = data.session_id
        return
      }
      handleEvent(data)
    } catch {
      // ignore parse errors
    }
  }

  ws.onclose = () => {
    isConnected.value = false
    globalError.value = '连接已断开，正在重连...'
    setTimeout(connectWebSocket, 3000)
  }

  ws.onerror = () => {
    isConnected.value = false
    globalError.value = '连接错误，请检查后端是否运行'
  }
}

function renderMarkdown(text: string): string {
  return marked.parse(text, { async: false }) as string
}

function scrollToBottom() {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}

function toggleReasoning(index: number) {
  const msg = messages.value[index]
  if (msg) {
    msg.showReasoning = !msg.showReasoning
  }
}

function toggleTools(index: number) {
  const msg = messages.value[index]
  if (msg) {
    msg.showTools = !msg.showTools
  }
}

function handleEnter(e: KeyboardEvent) {
  if (!e.shiftKey && !isProcessing.value) {
    sendMessage()
  }
}

function sendMessage() {
  const text = inputText.value.trim()
  if (!text || isProcessing.value || !ws || ws.readyState !== WebSocket.OPEN) return

  // 清除之前的错误
  globalError.value = ''

  // 显示用户消息到界面
  messages.value.push({ role: 'user', content: text })
  inputText.value = ''
  isLoading.value = true
  isProcessing.value = true
  scrollToBottom()

  // 创建 assistant 消息占位
  const assistantMsg: Message = {
    role: 'assistant',
    content: ''
  }
  messages.value.push(assistantMsg)
  isLoading.value = false

  // 发送：只传 session_id 和最新 message
  ws.send(JSON.stringify({
    session_id: sessionId.value,
    message: text
  }))
}

// 临时存储当前消息的工具调用，等待结果配对
let pendingToolCall: ToolCall | null = null

function handleEvent(event: any) {
  const lastMsg = messages.value[messages.value.length - 1]
  if (lastMsg.role !== 'assistant' || lastMsg.isError) return

  switch (event.type) {
    case 'text':
      lastMsg.content += event.content
      scrollToBottom()
      break

    case 'reasoning':
      if (!lastMsg.reasoning) {
        lastMsg.reasoning = ''
        lastMsg.showReasoning = false  // 默认折叠
      }
      lastMsg.reasoning += event.content
      scrollToBottom()
      break

    case 'tool_call':
      // 存储待配对的 tool_call
      pendingToolCall = {
        name: event.name,
        arguments: event.arguments
      }
      scrollToBottom()
      break

    case 'tool_result':
      // 与 pendingToolCall 配对
      if (pendingToolCall) {
        if (!lastMsg.toolPairs) {
          lastMsg.toolPairs = []
          lastMsg.showTools = false  // 默认折叠
        }
        lastMsg.toolPairs.push({
          call: pendingToolCall,
          result: event.result
        })
        pendingToolCall = null
        scrollToBottom()
      }
      break

    case 'done':
      // 清理未配对的 tool_call
      pendingToolCall = null
      isProcessing.value = false  // 处理完成
      break

    case 'error':
      // 错误作为独立消息显示（红色）
      messages.value.push({
        role: 'assistant',
        content: event.error || event.message || '未知错误',
        isError: true
      })
      pendingToolCall = null
      isProcessing.value = false  // 处理完成（出错）
      scrollToBottom()
      break
  }
}

onMounted(() => {
  connectWebSocket()
  if (inputRef.value) {
    inputRef.value.focus()
  }
})

onUnmounted(() => {
  if (ws) {
    ws.close()
  }
})
</script>

<style scoped>
.chat-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 全局错误提示 */
.global-error {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  background: #fff2f0;
  border-bottom: 1px solid #ffccc7;
  color: #cf1322;
  font-size: 14px;
}

.error-icon {
  font-size: 16px;
}

.error-text {
  flex: 1;
}

.error-close {
  background: none;
  border: none;
  color: #cf1322;
  cursor: pointer;
  font-size: 14px;
  padding: 2px 6px;
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.message {
  display: flex;
  gap: 12px;
  max-width: 100%;
}

.message.user {
  flex-direction: row-reverse;
}

.message.error {
  flex-direction: row;
}

.message.error .avatar {
  background: #fff2f0;
  border-color: #ffccc7;
}

.message.error .content {
  background: #fff2f0;
  border: 1px solid #ffccc7;
  color: #cf1322;
}

.error-text-content {
  font-family: monospace;
  font-size: 13px;
  white-space: pre-wrap;
  word-break: break-all;
}

.avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  flex-shrink: 0;
  background: #fff;
  border: 1px solid #e0e0e0;
}

.content {
  max-width: 80%;
  padding: 12px 16px;
  border-radius: 12px;
  line-height: 1.6;
}

.message.user .content {
  background: #007bff;
  color: #fff;
}

.message.assistant:not(.error) .content {
  background: #fff;
  border: 1px solid #e0e0e0;
  color: #333;
}

.message.assistant .content :deep(pre) {
  background: #f4f4f4;
  padding: 12px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 8px 0;
}

.message.assistant .content :deep(code) {
  font-family: 'Courier New', monospace;
  font-size: 13px;
}

.message.assistant .content :deep(p) {
  margin: 0 0 8px 0;
}

.message.assistant .content :deep(p:last-child) {
  margin-bottom: 0;
}

/* 思考内容折叠 */
.reasoning-section {
  margin-bottom: 12px;
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  overflow: hidden;
}

.reasoning-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 8px 12px;
  background: #f5f5f5;
  border: none;
  cursor: pointer;
  font-size: 13px;
  color: #666;
  text-align: left;
  transition: background 0.2s;
}

.reasoning-toggle:hover {
  background: #eeeeee;
}

.toggle-icon {
  font-size: 10px;
  color: #999;
}

.toggle-text {
  flex: 1;
}

.reasoning-badge {
  font-size: 11px;
  color: #999;
  background: #fff;
  padding: 2px 6px;
  border-radius: 4px;
}

.reasoning-content {
  padding: 10px 12px;
  background: #fafafa;
  border-top: 1px solid #e8e8e8;
}

.reasoning-content pre {
  margin: 0;
  font-family: 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.5;
  color: #666;
  white-space: pre-wrap;
  word-break: break-all;
}

/* 工具区域折叠 - 紧凑模式 */
.tools-section {
  margin-bottom: 8px;
}

.tools-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  background: #f0f5ff;
  border: 1px solid #d6e4ff;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  color: #2f54eb;
  line-height: 1.4;
  transition: background 0.2s;
}

.tools-toggle:hover {
  background: #d6e4ff;
}

.tools-badge {
  font-size: 11px;
  color: #2f54eb;
  opacity: 0.8;
}

.tools-content {
  margin-top: 8px;
  padding: 10px 12px;
  background: #f8f9fa;
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.tool-pair {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.tool-call, .tool-result {
  background: #fff;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 13px;
}

.tool-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
  font-weight: 500;
}

.tool-icon {
  font-size: 14px;
}

.tool-name {
  color: #555;
}

.tool-args {
  color: #666;
  font-family: monospace;
  white-space: pre-wrap;
  word-break: break-all;
}

.tool-output {
  color: #333;
  font-family: monospace;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 300px;
  overflow-y: auto;
  background: #f4f4f4;
  padding: 8px;
  border-radius: 4px;
  margin: 0;
}

.input-area {
  padding: 16px 20px;
  background: #fff;
  border-top: 1px solid #e0e0e0;
}

.input-box {
  display: flex;
  gap: 12px;
  align-items: flex-end;
}

.input-box textarea {
  flex: 1;
  padding: 12px 16px;
  border: 1px solid #d0d0d0;
  border-radius: 12px;
  resize: none;
  font-size: 15px;
  line-height: 1.5;
  max-height: 150px;
  font-family: inherit;
}

.input-box textarea:focus {
  outline: none;
  border-color: #007bff;
}

.input-box button {
  padding: 12px 24px;
  background: #007bff;
  color: #fff;
  border: none;
  border-radius: 12px;
  font-size: 15px;
  cursor: pointer;
  transition: background 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 80px;
  height: 44px;
}

.input-box button:hover:not(:disabled) {
  background: #0056b3;
}

.input-box button:disabled {
  background: #ccc;
  cursor: not-allowed;
}

/* 加载动画 */
.spinner {
  display: inline-block;
  width: 18px;
  height: 18px;
  border: 2px solid #fff;
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 4px 0;
}

.typing-indicator span {
  width: 8px;
  height: 8px;
  background: #999;
  border-radius: 50%;
  animation: bounce 1.4s infinite ease-in-out;
}

.typing-indicator span:nth-child(1) { animation-delay: 0s; }
.typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
.typing-indicator span:nth-child(3) { animation-delay: 0.4s; }

@keyframes bounce {
  0%, 80%, 100% { transform: scale(0); }
  40% { transform: scale(1); }
}
</style>
