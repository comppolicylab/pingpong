<script>
  import '../app.pcss';
  import Sidebar from '../lib/components/Sidebar.svelte';
  import Main from '$lib/components/Main.svelte';
  import { SvelteToast } from '@zerodevx/svelte-toast';
  import { onMount } from 'svelte';
  import { detectBrowser } from '$lib/stores/general';

  export let data;

  onMount(() => {
    detectBrowser();
  });

  $: showSidebar =
    (data.me &&
      data.me.user &&
      !data.needsOnboarding &&
      (!data.needsAgreements || !data.doNotShowSidebar)) ||
    (data.isPublicPage && !data.doNotShowSidebar) ||
    data.isSharedAssistantPage ||
    data.isSharedThreadPage;
  $: showStatusPage = data.me?.user;
  $: showBackground = data.isSharedAssistantPage || data.isSharedThreadPage;
</script>

<SvelteToast />
{#if showSidebar}
  <div class=" w-full flex h-full lg:gap-4 md:h-[calc(100vh-3rem)]">
    <div class="sidebar basis-[320px] shrink-0 grow-0 min-w-0">
      <Sidebar {data} />
    </div>
    <div class="main-content shrink grow min-w-0">
      <Main>
        <slot />
      </Main>
    </div>
  </div>
  {#if showStatusPage && data.hasNonComponentIncidents}
    <script src="https://pingpong-hks.statuspage.io/embed/script.js"></script>
  {/if}
{:else if showBackground}
  <Main>
    <slot />
  </Main>
{:else}
  <slot />
{/if}

<style lang="css">
  :root {
    --toastBackground: #22c55e;
    --toastBorderRadius: 0.5rem;
    --toastBarBackground: #1d9e48;
  }

  @media print {
    .sidebar {
      display: none !important;
    }
    .main-content {
      flex-basis: 100% !important;
      max-width: 100% !important;
    }
  }
</style>
