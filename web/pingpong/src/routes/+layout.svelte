<script>
  import '../app.pcss';
  import Sidebar from './Sidebar.svelte';
  import Main from '$lib/components/Main.svelte';
  import { SvelteToast } from '@zerodevx/svelte-toast';

  export let data;
</script>

<SvelteToast />
{#if data.me.user}
  <div class="flex h-screen">
    <Sidebar {data} />
    <Main>
      <slot />
    </Main>
  </div>
{:else}
  <slot />
{/if}

<style lang="css">
  :root {
    --toastBackground: #22c55e;
    --toastBorderRadius: 0.5rem;
    --toastBarBackground: #1d9e48;
  }
</style>
