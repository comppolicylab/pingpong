<script>
  import "../app.pcss";
  import Menu from './Menu.svelte';
  import Main from './Main.svelte';

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
