<script lang="ts">
	import ThreadLandingPage from '$lib/components/ThreadLandingPage.svelte';

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

<ThreadLandingPage {data} />
