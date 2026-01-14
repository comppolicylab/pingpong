<script lang="ts">
  import { slide } from 'svelte/transition';
  import { ChevronDownOutline, GlobeOutline } from 'flowbite-svelte-icons';
  import type { WebSearchActionSearchSource, WebSearchCallItem } from '$lib/api';
  import WebSourceChip from './WebSourceChip.svelte';
  import { SvelteSet } from 'svelte/reactivity';

  export let content: WebSearchCallItem;
  export let forceOpen = false;
  export let forceEagerImages = false;

  let open = false;
  let previousOpen: boolean | null = null;
  $: {
    if (forceOpen) {
      if (previousOpen === null) {
        previousOpen = open;
      }
      open = true;
    } else if (previousOpen !== null) {
      open = previousOpen;
      previousOpen = null;
    }
  }
  const handleClick = () => (open = !open);

  const deduplicateSources = (sources?: WebSearchActionSearchSource[]) => {
    if (!sources) return [];

    const seen = new SvelteSet<string>();
    return sources.filter(({ url }) => {
      if (seen.has(url)) return false;
      seen.add(url);
      return true;
    });
  };

  $: uniqueSources =
    content?.action?.type === 'search' ? deduplicateSources(content.action.sources) : [];
</script>

<div class="my-3">
  {#if content.action && content.action.type === 'search' && uniqueSources.length > 0}
    <div class="flex items-center gap-2">
      <GlobeOutline class="h-4 w-4 text-gray-600" />
      <button class="flex flex-row items-bottom" onclick={handleClick}>
        {#if content.status === 'completed'}
          <span class="text-sm text-left font-medium text-gray-600"
            >Searched{content.action.query
              ? ` web for ${content.action.query}`
              : ' the web'}{#if open}<span
                >{content.action.sources
                  ? ` across ${content.action.sources.length} ${content.action.sources.length === 1 ? 'source' : 'sources'}`
                  : ''}...</span
              >{/if}</span
          >
        {:else if content.status === 'failed'}
          <span class="text-sm font-medium text-yellow-600">Web search failed</span>
        {:else if content.status === 'incomplete'}
          <span class="text-sm font-medium text-yellow-600">Web search was canceled</span>
        {:else}
          <span class="text-sm font-medium shimmer"
            >Searching web{content.action.query ? ` for ${content.action.query}` : ''}...</span
          >
        {/if}
        {#if open}
          <ChevronDownOutline class="transform rotate-180 text-gray-600" />
        {:else}
          <ChevronDownOutline class="text-gray-600" />
        {/if}
      </button>
    </div>
    {#if open}
      <div
        class="ml-2 py-2 border-l border-gray-200 pl-4 text-sm text-gray-600 font-light flex flex-row flex-wrap gap-x-2 gap-y-1 w-3/4"
        transition:slide={{ duration: 250, axis: 'y' }}
      >
        {#if uniqueSources.length === 0}
          <div class="py-0.5" transition:slide={{ duration: 250, axis: 'y' }}>
            No sources found.
          </div>
        {:else}
          {#each uniqueSources as source, i (source.url)}
            <div class="py-0.5" transition:slide={{ delay: i * 80, duration: 250, axis: 'y' }}>
              <WebSourceChip {source} type="list" forceEagerLoad={forceEagerImages} />
            </div>
          {/each}
        {/if}
      </div>
    {/if}
  {:else if content.action && content.action.type}
    <div class="flex items-center gap-2">
      <GlobeOutline class="h-4 w-4 text-gray-600" />
      <div class="flex flex-row items-bottom">
        {#if content.action.type === 'search'}
          {#if content.status === 'completed'}
            <span class="text-sm font-medium text-gray-600"
              >Searched{content.action.query
                ? ` web for ${content.action.query}`
                : ' the web'}</span
            >
          {:else if content.status === 'failed'}
            <span class="text-sm font-medium text-yellow-600">Web search failed</span>
          {:else if content.status === 'incomplete'}
            <span class="text-sm font-medium text-yellow-600">Web search was canceled</span>
          {:else}
            <span class="text-sm font-medium shimmer">Searching web...</span>
          {/if}
        {:else if content.action.type === 'find'}
          {#if content.status === 'completed'}
            <span
              class="flex flex-row flex-wrap items-center gap-x-2 gap-y-1 text-sm font-medium text-gray-600"
              ><span>Looked closer through</span>{#if content.action.url}<WebSourceChip
                  source={{ url: content.action.url, type: 'url' }}
                  type="list"
                  forceEagerLoad={forceEagerImages}
                />{:else}web sources{/if}{#if content.action.pattern}
                for {content.action.pattern}{/if}</span
            >
          {:else if content.status === 'failed'}
            <span class="text-sm font-medium text-yellow-600">Web search failed</span>
          {:else if content.status === 'incomplete'}
            <span class="text-sm font-medium text-yellow-600">Web search was canceled</span>
          {:else}
            <span class="text-sm font-medium shimmer">Digging through web sources...</span>
          {/if}
        {:else if content.action.type === 'open_page'}
          {#if content.status === 'completed'}
            <span
              class="flex flex-row flex-wrap items-center gap-x-2 gap-y-1 text-sm font-medium text-gray-600"
              >{#if content.action.url}<span>Opened</span><WebSourceChip
                  source={{ url: content.action.url, type: 'url' }}
                  type="list"
                  forceEagerLoad={forceEagerImages}
                />{:else}Looked through web sources{/if}</span
            >
          {:else if content.status === 'failed'}
            <span class="text-sm font-medium text-yellow-600">Web search failed</span>
          {:else if content.status === 'incomplete'}
            <span class="text-sm font-medium text-yellow-600">Web search was canceled</span>
          {:else}
            <span class="text-sm font-medium shimmer">Looking through web sources...</span>
          {/if}
        {/if}
      </div>
    </div>
  {:else}
    <div class="flex items-center gap-2">
      <GlobeOutline class="h-4 w-4 text-gray-600" />
      <div class="flex flex-row items-bottom">
        {#if content.status === 'completed'}
          <span class="text-sm font-medium text-gray-600">Searched the web</span>
        {:else if content.status === 'failed'}
          <span class="text-sm font-medium text-yellow-600">Web search failed</span>
        {:else if content.status === 'incomplete'}
          <span class="text-sm font-medium text-yellow-600">Web search was canceled</span>
        {:else}
          <span class="text-sm font-medium shimmer">Searching web...</span>
        {/if}
      </div>
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
    background: #4b5563 -webkit-gradient(
        linear,
        100% 0,
        0 0,
        from(#5d5d5d),
        color-stop(0.4, #ffffffbf),
        to(#4b5563),
        color-stop(0.6, #ffffffbf),
        to(#4b5563)
      );
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
