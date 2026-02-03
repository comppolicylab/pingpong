<script lang="ts">
	import ThreadLandingPage from '$lib/components/ThreadLandingPage.svelte';

	/**
	 * Application data.
	 */
	export let data;
	import { onMount } from 'svelte';
	import { ltiHeaderComponent, ltiHeaderProps } from '$lib/stores/ltiHeader';

	onMount(() => {
		ltiHeaderComponent.set(null);
		ltiHeaderProps.set({});
	});
</script>

<ThreadLandingPage {data} />
