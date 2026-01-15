<script lang="ts">
	import ThreadLandingPage from '$lib/components/ThreadLandingPage.svelte';

	let { data } = $props();
</script>

<ThreadLandingPage {data} />
