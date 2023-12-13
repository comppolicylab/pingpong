<script>
  import "../app.pcss";
  import TopMatter from "./TopMatter.svelte";

  export let data;

</script>

{#if data.me.user}
  <TopMatter />
{/if}
<slot></slot>
