<script lang="ts">
	import { createEventDispatcher, onMount } from 'svelte';
	import * as api from '$lib/api';

	export let classId: number;
	export let assistants: api.Assistant[];
	const dispatch = createEventDispatcher<{ refresh: api.Assistants }>();
	let mounted = false;
	let timer: ReturnType<typeof setTimeout> | null = null;
	let inFlight = false;
	let failures = 0;
	$: pending = assistants.some((assistant) =>
		[assistant.lecture_slide_deck?.status, assistant.lecture_video?.status].some(
			(status) => status === 'uploaded' || status === 'processing'
		)
	);

	function stop() {
		if (timer !== null) clearTimeout(timer);
		timer = null;
	}

	function schedule() {
		if (!mounted || !pending || document.hidden || timer !== null || inFlight) return;
		timer = setTimeout(refresh, Math.min(4000 * 2 ** failures, 30000));
	}

	async function refresh() {
		timer = null;
		if (!mounted || !pending || document.hidden) return;
		const requestedClassId = classId;
		inFlight = true;
		try {
			const result = api.explodeResponse(await api.getAssistants(fetch, requestedClassId));
			if (mounted && requestedClassId === classId) dispatch('refresh', result);
			failures = 0;
		} catch {
			failures = Math.min(failures + 1, 3);
		} finally {
			inFlight = false;
			schedule();
		}
	}

	$: if (mounted && pending && classId) schedule();
	$: if (!pending) stop();

	onMount(() => {
		mounted = true;
		const visibilityChanged = () => {
			stop();
			schedule();
		};
		document.addEventListener('visibilitychange', visibilityChanged);
		return () => {
			mounted = false;
			stop();
			document.removeEventListener('visibilitychange', visibilityChanged);
		};
	});
</script>
