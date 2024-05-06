<script lang="ts">
  import ThreadHeader from '$lib/components/ThreadHeader.svelte';

  export let data;
</script>

<ThreadHeader current={data.class} classes={data.classes} />
<slot />
