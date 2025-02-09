<script lang="ts">
  import DOMPurify from '$lib/purify';
  import { Heading, Li, List } from 'flowbite-svelte'; // eslint-disable-line @typescript-eslint/no-unused-vars

  /**
   * Content to render.
   */
  export let html: string | Promise<string>;

  let sanitized: string;

  const flowbiteSvelteTags = ['Heading', 'List', 'Li'];

  DOMPurify.addHook('uponSanitizeAttribute', (node, data) => {
    if (data.attrName === 'customsize' && node.nodeName !== 'HEADING') {
      data.keepAttr = false; // Remove the attribute if not on <Heading>
    }
  });

  // Sanitize the document.
  $: {
    if (typeof html === 'string') {
      sanitized = DOMPurify.sanitize(html, {
        ADD_TAGS: flowbiteSvelteTags,
        ADD_ATTR: ['customsize', 'tag']
      });
    } else {
      sanitized = '';
      html.then((content) => {
        sanitized = DOMPurify.sanitize(content, {
          ADD_TAGS: flowbiteSvelteTags,
          ADD_ATTR: ['customsize', 'tag']
        });
      });
    }
    // Fix Flowbite Svelte tags
    sanitized = sanitized
      .replace(/<heading\b/gi, '<Heading')
      .replace(/<\/heading>/gi, '</Heading>')
      .replace(/<list\b/gi, '<List')
      .replace(/<\/list>/gi, '</List>')
      .replace(/<li\b/gi, '<Li')
      .replace(/<\/li>/gi, '</Li>');
  }
</script>

<div>
  <!-- eslint-disable-next-line svelte/no-at-html-tags -->
  {@html sanitized}
</div>
