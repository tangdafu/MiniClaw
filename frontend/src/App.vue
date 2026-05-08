<template>
  <div class="app">
    <header class="header">
      <h1>🤖 MiniClaw Agent</h1>
      <p class="subtitle">与大模型对话，自动调用工具</p>
    </header>
    <ChatView />
  </div>
</template>

<script setup lang="ts">
import ChatView from './components/ChatView.vue'
</script>

<style scoped>
.app {
  max-width: 900px;
  margin: 0 auto;
  height: 100vh;
  display: flex;
  flex-direction: column;
}

.header {
  padding: 16px 24px;
  background: #fff;
  border-bottom: 1px solid #e0e0e0;
  text-align: center;
}

.header h1 {
  font-size: 20px;
  font-weight: 600;
  color: #1a1a1a;
}

.subtitle {
  font-size: 13px;
  color: #666;
  margin-top: 4px;
}
</style>
