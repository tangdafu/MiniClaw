<template>
  <section class="reasoning-block">
    <button class="reasoning-toggle" @click="isOpen = !isOpen">
      <span class="chevron">{{ isOpen ? '⌄' : '›' }}</span>
      <span class="label">思考过程</span>
      <span class="meta">{{ reasoning.length }} 字</span>
    </button>
    <pre v-if="isOpen" class="reasoning-content">{{ reasoning }}</pre>
  </section>
</template>

<script setup lang="ts">
import { ref } from 'vue'

defineProps<{
  reasoning: string
}>()

const isOpen = ref(false)
</script>

<style scoped>
.reasoning-block {
  margin-bottom: var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface-muted);
  overflow: hidden;
}

.reasoning-toggle {
  width: 100%;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 9px 11px;
  border: 0;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 13px;
  text-align: left;
}

.label {
  font-weight: 650;
}

.meta {
  margin-left: auto;
  color: var(--text-tertiary);
}

.chevron {
  color: var(--accent);
  font-size: 17px;
  line-height: 1;
}

.reasoning-content {
  max-height: 360px;
  overflow: auto;
  margin: 0;
  padding: 12px;
  color: var(--text-secondary);
  background: rgba(255, 255, 255, 0.62);
  border-top: 1px solid var(--border);
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
