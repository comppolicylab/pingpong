<script lang="ts">
  import { markdown } from '$lib/markdown';
  import autoRender from 'katex/contrib/auto-render';
  import Sanitize from './Sanitize.svelte';

  export let content = '';

  const renderKatex = (node: HTMLElement) => {
    autoRender(node, {
      delimiters: [
        { left: '$$', right: '$$', display: true },
        { left: '$', right: '$', display: false },
        { left: '\\(', right: '\\)', display: false },
        { left: '\\[', right: '\\]', display: true }
      ]
    });
  };

  const renderMarkdownNode = (node: HTMLElement, newContent: string) => {
    renderKatex(node);

    return {
      update() {
        renderKatex(node);
      }
    };
  };
</script>

<div class="markdown max-w-full" use:renderMarkdownNode={content}>
  <Sanitize html={markdown(content)} />
</div>
