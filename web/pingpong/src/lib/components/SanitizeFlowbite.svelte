<script lang="ts">
  import DOMPurify from '$lib/purify';

  /**
   * Content to render.
   */
  export let html: string | Promise<string>;

  let sanitized: string;

  const flowbiteSvelteTags = [
    'Heading',
    'Li',
  ];

  DOMPurify.addHook('uponSanitizeAttribute', (node, data) => {
    if (data.attrName === 'customsize' && node.nodeName !== 'HEADING') {
      data.keepAttr = false; // Remove the attribute if not on <Heading>
    }
  });

  // Sanitize the document.
  $: {
    if (typeof html === 'string') {
      sanitized = DOMPurify.sanitize(html, { ADD_TAGS: flowbiteSvelteTags, ADD_ATTR: ['customsize'] });
    } else {
      sanitized = '';
      html.then((content) => {
        sanitized = DOMPurify.sanitize(content, { ADD_TAGS: flowbiteSvelteTags});
      });
    }
  }
</script>

<div>
  <!-- eslint-disable-next-line svelte/no-at-html-tags -->
  {@html sanitized}
</div>
