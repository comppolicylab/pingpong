<script lang="ts">
  import DOMPurify from 'isomorphic-dompurify';

  /**
   * Content to render.
   */
  export let html: string | Promise<string>;

  let sanitized: string;

  // Sanitize the document.
  $: {
    if (typeof html === 'string') {
      sanitized = DOMPurify.sanitize(html);
    } else {
      sanitized = '';
      html.then((content) => {
        sanitized = DOMPurify.sanitize(content);
      });
    }
  }
</script>

<div>
  <!-- eslint-disable-next-line svelte/no-at-html-tags -->
  {@html sanitized}
</div>
