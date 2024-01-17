<script lang="ts">
  import {markdown} from "$lib/markdown";
  import autoRender from "katex/contrib/auto-render";

  export let content = "";

  const renderKatex = (node: HTMLElement) => {
    autoRender(node, {
       delimiters: [
        {left: '$$', right: '$$', display: true},
        {left: '$', right: '$', display: false},
        {left: '\\(', right: '\\)', display: false},
        {left: '\\[', right: '\\]', display: true}
      ],
    });
  };

  const renderMarkdownNode = (node: HTMLElement) => {
    renderKatex(node);

    return {
      update() {
        renderKatex(node);
      }
    }
  };
</script>

<div class="markdown max-w-full" use:renderMarkdownNode={content}>
  {@html markdown(content)}
</div>

<style lang="css">
  :global(.katex-display) {
    display: block;
    width: 100%;
    margin: 1.5rem 0;
  }

  :global(.markdown p) {
    margin-bottom: 1rem;
  }

  :global(.markdown code) {
    border-radius: 0.25rem;
  }
</style>
