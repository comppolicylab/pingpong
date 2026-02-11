<script lang="ts">
	import ThreadDetailPage from '$lib/components/ThreadDetailPage.svelte';

	/**
	 * Application data.
	 */
	export let data;
	import { onMount } from 'svelte';
	import { ltiHeaderState } from '$lib/stores/ltiHeader';

	onMount(() => {
		ltiHeaderState.set({ kind: 'none' });
	});
</script>

<ThreadDetailPage {data} />
