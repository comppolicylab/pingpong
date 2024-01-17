<script lang="ts">
  import hljs from "highlight.js";

  export let text: string = "";
  export let lang: string = "";

  let highlighted: string = text;
  $: {
    if (lang) {
      highlighted = hljs.highlight(text, { language: lang }).value;
    } else {
      highlighted = hljs.highlightAuto(text).value;
    }
  }
</script>

<div class="my-2">
<div style="background-color: #f3f3f3" class="text-sm py-1 pr-2 text-right rounded-t font-mono text-gray-700 border-b border-gray-200 font-bold">
  {lang}
</div>
<pre><code class="rounded-b hljs">{@html highlighted}</code></pre>
</div>
