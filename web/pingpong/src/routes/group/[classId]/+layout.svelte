<script lang="ts">
  import ThreadHeader from '$lib/components/ThreadHeader.svelte';
  import { page } from '$app/stores';

  export let data;

  // Figure out if we're on the assistant page.
  // When we are, we want to show the "Manage Class" link.
  // For every other page, we show the "View Class Page" link.
  $: isOnClassPage = $page.url.pathname === `/group/${data.class?.id}/assistant`;
</script>

<div class="relative pb-2 h-full w-full flex flex-col">
  <ThreadHeader
    current={data.class}
    classes={data.classes}
    canManage={data.canManage}
    {isOnClassPage}
  />
  <slot />
</div>
