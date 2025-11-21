<script lang="ts">
  import { slide } from 'svelte/transition';
  import { ChevronDownOutline, GlobeOutline } from 'flowbite-svelte-icons';
  import type { WebSearchCallItem } from '$lib/api';
  import WebSourceChip from './WebSourceChip.svelte';

  export let content: WebSearchCallItem;

  let open = false;
  const toggle = () => (open = !open);

  const statusText = () => {
    switch (content.status) {
      case 'completed':
        return 'Searched the web';
      case 'failed':
        return 'Web search failed';
      case 'incomplete':
        return 'Web search was canceled';
      default:
        return 'Searching the web...';
    }
  };
</script>

  <div class="my-3">
    <div class="flex items-center gap-2">
      <GlobeOutline class="h-4 w-4 text-gray-600" />
    <button class="flex flex-row items-center gap-2" on:click={toggle}>
      <span
        class={`text-sm font-medium ${
          content.status === 'failed'
            ? 'text-red-600'
            : content.status === 'incomplete'
              ? 'text-yellow-600'
              : 'text-gray-600'
        } ${content.status === 'completed' ? '' : 'shimmer'}`}
        >{statusText()}</span
      >
      <ChevronDownOutline class={`text-gray-600 transition ${open ? 'rotate-180' : ''}`} />
    </button>
  </div>
  {#if open}
    <div
      class="ml-2 mt-1 border-l border-gray-200 pl-4 text-sm text-gray-600 font-light space-y-2"
      transition:slide={{ duration: 250 }}
    >
      {#if content.action_type === 'search' && content.query}
        <div class="leading-5">Query: {content.query}</div>
      {/if}
      {#if content.action_type === 'find'}
        {#if content.pattern}
          <div class="leading-5">Pattern: {content.pattern}</div>
        {/if}
        {#if content.url}
          <div class="leading-5 break-all">Within: {content.url}</div>
        {/if}
      {/if}
      {#if content.action_type === 'open_page' && content.url}
        <div class="leading-5 break-all">Opened: {content.url}</div>
      {/if}
      {#if content.sources && content.sources.length > 0}
        <div class="flex flex-wrap gap-2 pt-1">
          {#each content.sources as source (source.url || source.name || Math.random())}
            <WebSourceChip {source} />
          {/each}
        </div>
      {/if}
    </div>
  {/if}
</div>

<style lang="css">
  .shimmer {
    color: transparent;
    -webkit-text-fill-color: transparent;
    animation-delay: 0s;
    animation-duration: 2s;
    animation-iteration-count: infinite;
    animation-name: shimmer;
    background: #4b5563 -webkit-gradient(linear, 100% 0, 0 0, from(#5d5d5d), color-stop(0.4, #ffffffbf), to(#4b5563),
        color-stop(0.6, #ffffffbf), to(#4b5563));
    -webkit-background-clip: text;
    background-clip: text;
    background-position: -100% 0;
    background-position: unset top;
    background-repeat: no-repeat;
    background-size: 50% 200%;
  }

  @keyframes shimmer {
    0% {
      background-position: -100% 0;
    }
    100% {
      background-position: 250% 0;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .shimmer {
      animation: none;
    }
  }

  .shimmer:hover {
    -webkit-text-fill-color: #374151;
    color: #374151;
    background: 0 0;
  }
</style>
