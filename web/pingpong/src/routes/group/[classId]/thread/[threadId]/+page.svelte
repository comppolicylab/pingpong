<script lang="ts">
	import ThreadDetailPage from '$lib/components/ThreadDetailPage.svelte';

	let { data } = $props();
</script>

<ThreadDetailPage {data} />
