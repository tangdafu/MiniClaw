<template>
  <div class="markdown-content" v-html="html"></div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { marked } from 'marked'

const props = defineProps<{
  content: string
}>()

const html = computed(() => marked.parse(props.content, { async: false }) as string)
</script>

<style scoped>
.markdown-content {
  color: var(--text-primary);
  line-height: 1.72;
  overflow-wrap: anywhere;
}

.markdown-content :deep(h1),
.markdown-content :deep(h2),
.markdown-content :deep(h3) {
  margin: 1.1em 0 0.5em;
  color: var(--text-strong);
  line-height: 1.25;
  letter-spacing: -0.03em;
}

.markdown-content :deep(h1:first-child),
.markdown-content :deep(h2:first-child),
.markdown-content :deep(h3:first-child),
.markdown-content :deep(p:first-child) {
  margin-top: 0;
}

.markdown-content :deep(h1) { font-size: 24px; }
.markdown-content :deep(h2) { font-size: 20px; }
.markdown-content :deep(h3) { font-size: 17px; }

.markdown-content :deep(p) {
  margin: 0 0 0.85em;
}

.markdown-content :deep(ul),
.markdown-content :deep(ol) {
  margin: 0.6em 0 0.9em 1.3em;
  padding: 0;
}

.markdown-content :deep(li) {
  margin: 0.28em 0;
}

.markdown-content :deep(a) {
  color: var(--accent);
  text-decoration: none;
  border-bottom: 1px solid rgba(37, 99, 235, 0.24);
}

.markdown-content :deep(a:hover) {
  border-color: var(--accent);
}

.markdown-content :deep(blockquote) {
  margin: 1em 0;
  padding: 0.75em 1em;
  color: var(--text-secondary);
  background: var(--surface-muted);
  border-left: 3px solid var(--accent-soft);
  border-radius: 0 var(--radius-md) var(--radius-md) 0;
}

.markdown-content :deep(code) {
  padding: 0.15em 0.38em;
  border-radius: 7px;
  background: #eef2ff;
  color: #3730a3;
  font-family: var(--font-mono);
  font-size: 0.9em;
}

.markdown-content :deep(pre) {
  margin: 1em 0;
  padding: 14px 16px;
  overflow-x: auto;
  background: #0f172a;
  color: #dbeafe;
  border-radius: var(--radius-lg);
  box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.2);
}

.markdown-content :deep(pre code) {
  padding: 0;
  background: transparent;
  color: inherit;
  font-size: 13px;
}

.markdown-content :deep(table) {
  width: 100%;
  display: block;
  overflow-x: auto;
  border-collapse: collapse;
  margin: 1em 0;
}

.markdown-content :deep(th),
.markdown-content :deep(td) {
  padding: 9px 11px;
  border: 1px solid var(--border);
  text-align: left;
  vertical-align: top;
}

.markdown-content :deep(th) {
  background: var(--surface-muted);
  color: var(--text-strong);
}

.markdown-content :deep(hr) {
  border: 0;
  border-top: 1px solid var(--border);
  margin: 1.4em 0;
}
</style>
