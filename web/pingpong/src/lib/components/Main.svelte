<script lang="ts">
  import { appMenuOpen } from '$lib/stores/general';
  import { navigating } from '$app/stores';
  import { Pulse } from 'svelte-loading-spinners';
  import { blur } from 'svelte/transition';
  import { loading, loadingMessage } from '$lib/stores/general';
  import { onMount } from 'svelte';

  export let data;

  let inIframe = false;
  $: isLTIInactivePage = data?.isLTIInactivePage ?? false;
  onMount(() => {
    inIframe = window.self !== window.top;
  });
</script>

<div
  class={`main-panel transition-all absolute left-0 top-24 z-10 w-[calc(100%-2rem)] ml-4 mr-4 h-[calc(100%-6rem)] overflow-hidden print:!static print:!w-full print:!h-auto print:!m-0 print:!p-0 print:!overflow-visible print:!top-0 print:!left-0 print:!z-auto  ${
    $appMenuOpen ? 'left-[90%]' : ''
  } ${!inIframe || isLTIInactivePage ? 'lg:h-full lg:static' : ''}`}
>
  <div
    class="h-full flex-grow bg-white rounded-t-4xl overflow-hidden relative print:!overflow-visible print:!h-auto print:!rounded-none print:!bg-transparent"
  >
    {#if !!$navigating || $loading}
      <div
        class="absolute top-0 left-0 flex h-full w-full items-center bg-white bg-opacity-75 z-[9999] print:!hidden"
      >
        <div class="m-auto flex flex-col gap-5 items-center" transition:blur={{ amount: 10 }}>
          <Pulse color="#0ea5e9" />
          {#if $loadingMessage}
            <p>{$loadingMessage}</p>
          {/if}
        </div>
      </div>
    {/if}
    <slot />
  </div>
</div>
