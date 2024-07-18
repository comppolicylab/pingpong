<script lang="ts">
  import { appMenuOpen } from '$lib/stores/general';
  import { navigating } from '$app/stores';
  import { Pulse } from 'svelte-loading-spinners';
  import { blur } from 'svelte/transition';
  import { loading, loadingMessage } from '$lib/stores/general';
</script>

<div
  class={`main-panel transition-all absolute left-0 top-24 z-10 w-[calc(100%-2rem)] ml-4 mr-4 h-[calc(100%-6rem)] lg:h-full overflow-hidden lg:static ${
    $appMenuOpen ? 'left-[90%]' : ''
  }`}
>
  <div class="h-full flex-grow bg-white rounded-t-4xl overflow-hidden relative">
    {#if !!$navigating || $loading}
      <div
        class="absolute top-0 left-0 flex h-full w-full items-center bg-white bg-opacity-75 z-50"
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
