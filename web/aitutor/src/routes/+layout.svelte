<script>
  import "../app.pcss";
  import Sidebar from '$lib/components/Sidebar.svelte';
  import Main from '$lib/components/Main.svelte';

  export let data;
</script>

{#if data.me.user}
  <div class="flex h-screen">
    <Sidebar {data} />
    <Main>
      <slot></slot>
    </Main>
  </div>
{:else}
  <slot></slot>
{/if}
