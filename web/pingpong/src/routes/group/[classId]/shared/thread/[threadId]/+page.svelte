<script lang="ts">
	import ThreadDetailPage from '$lib/components/ThreadDetailPage.svelte';

	/**
	 * Application data.
	 */
	export let data;
	import { onMount } from 'svelte';
	import { headerState } from '$lib/stores/header';

	onMount(() => {
		headerState.set({ kind: 'none' });
	});
</script>

<ThreadDetailPage {data} />
