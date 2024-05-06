<script lang="ts">
  import PageHeader from '$lib/components/PageHeader.svelte';

  export let data;
</script>

<PageHeader current={data.class} classes={data.classes} />
<slot />
