<script>
  import "../app.pcss";
  import Menu from '$lib/components/Menu.svelte';
  import Main from '$lib/components/Main.svelte';

  export let data;
</script>

{#if data.me.user}
  <div class="flex h-screen">
    <Menu {data} />
    <Main>
      <slot></slot>
    </Main>
  </div>
{:else}
  <slot></slot>
{/if}
