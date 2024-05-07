<script lang="ts">
  import ThreadHeader from '$lib/components/ThreadHeader.svelte';

  export let data;
</script>

<div class="relative pb-8 h-full w-full">
  <ThreadHeader current={data.class} classes={data.classes} canManage={data.canManage} />
  <slot />
</div>
