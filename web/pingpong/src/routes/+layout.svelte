<script>
  import '../app.pcss';
  import Sidebar from '../lib/components/Sidebar.svelte';
  import Main from '$lib/components/Main.svelte';
  import { SvelteToast } from '@zerodevx/svelte-toast';

  export let data;
</script>

<SvelteToast />
{#if data.me.user}
  <!---<div class="h-full lg:grid lg:w-full lg:grid-cols-[320px_1fr] lg:gap-4 ">-->
  <div class=" w-full flex lg:gap-4 h-[calc(100vh-3rem)]">
    <div class="basis-[320px] shrink-0 grow-0">
      <Sidebar {data} />
    </div>
    <div class="basis-full grow">
      <Main>
        <slot />
      </Main>
    </div>
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
