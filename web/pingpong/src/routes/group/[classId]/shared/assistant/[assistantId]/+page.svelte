<script lang="ts">
	import ThreadLandingPage from '$lib/components/ThreadLandingPage.svelte';

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

<ThreadLandingPage {data} />
