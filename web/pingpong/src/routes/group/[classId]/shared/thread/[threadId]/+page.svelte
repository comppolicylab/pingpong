<script lang="ts">
	import ThreadDetailPage from '$lib/components/ThreadDetailPage.svelte';

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

<ThreadDetailPage {data} />
