<script lang="ts">
  import ThreadHeader from '$lib/components/ThreadHeader.svelte';
  import { page } from '$app/stores';
  import { onMount, setContext } from 'svelte';
  import { writable } from 'svelte/store';

  export let data;

  let headerEl: HTMLDivElement;
  const headerHeightStore = writable(0);

  onMount(() => {
    headerHeightStore.set(headerEl?.offsetHeight ?? 0);
  });

  setContext('headerHeightStore', headerHeightStore);

  // Figure out if we're on the assistant page.
  // When we are, we want to show the "Manage Class" link.
  // For every other page, we show the "View Class Page" link.
  $: isOnClassPage = $page.url.pathname === `/group/${data.class?.id}/assistant`;
</script>

<div class="relative h-full w-full flex flex-col">
  {#if !(data.isSharedAssistantPage || data.isSharedThreadPage)}
    <div bind:this={headerEl}>
      <ThreadHeader
        current={data.class}
        classes={data.classes}
        canManage={data.canManage}
        {isOnClassPage}
        isSharedPage={data.isSharedAssistantPage || data.isSharedThreadPage}
      />
    </div>
  {/if}
  <slot />
</div>
