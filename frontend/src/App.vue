<template>
  <div class="app">
    <header class="header">
      <div>
        <p class="product-label">Local Agent Console</p>
        <h1>MiniClaw Agent</h1>
      </div>
      <p class="subtitle">会话、工具调用和上下文都在一个干净的工作台里。</p>
    </header>
    <ChatView />
  </div>
</template>

<script setup lang="ts">
import ChatView from './components/ChatView.vue'
</script>

<style scoped>
.app {
  width: 100%;
  max-width: 1440px;
  margin: 0 auto;
  height: 100vh;
  display: flex;
  flex-direction: column;
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 18px 28px 0;
}

.header h1 {
  margin: 0;
  color: var(--text-strong);
  font-size: 24px;
  font-weight: 800;
  letter-spacing: -0.05em;
}

.product-label {
  margin: 0 0 3px;
  color: var(--accent);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.subtitle {
  max-width: 420px;
  margin: 0;
  color: var(--text-secondary);
  font-size: 14px;
  line-height: 1.5;
  text-align: right;
}

@media (max-width: 720px) {
  .header {
    align-items: flex-start;
    flex-direction: column;
    gap: 8px;
    padding: 14px 14px 0;
  }

  .subtitle {
    text-align: left;
  }
}
</style>
