<script lang="ts">
	import ThreadLandingPage from '$lib/components/ThreadLandingPage.svelte';

	
	interface Props {
		/**
	 * Application data.
	 */
		data: any;
	}

	let { data }: Props = $props();
</script>

<ThreadLandingPage {data} />
