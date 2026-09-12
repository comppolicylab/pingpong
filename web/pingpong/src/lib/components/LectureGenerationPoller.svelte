<script lang="ts">
	import { createEventDispatcher, onMount } from 'svelte';
	import { RefreshOutline } from 'flowbite-svelte-icons';
	import * as api from '$lib/api';

	export let classId: number;
	export let assistants: api.Assistant[];
	const dispatch = createEventDispatcher<{ refresh: api.Assistants }>();
	let mounted = false;
	let timer: ReturnType<typeof setTimeout> | null = null;
	export let inFlight = false;
	export let secondsUntilRefresh: number | null = null;
	export let showStatus = true;
	let countdownTimer: ReturnType<typeof setInterval> | null = null;
	let failures = 0;
	$: pending = assistants.some((assistant) =>
		[assistant.lecture_slide_deck?.status, assistant.lecture_video?.status].some(
			(status) => status === 'uploaded' || status === 'processing'
		)
	);

	function stop() {
		if (timer !== null) clearTimeout(timer);
		timer = null;
		if (countdownTimer !== null) clearInterval(countdownTimer);
		countdownTimer = null;
		secondsUntilRefresh = null;
	}

	function schedule() {
		if (!mounted || !pending || document.hidden || timer !== null || inFlight) return;
		const delay = Math.min(5000 * 2 ** failures, 30000);
		const deadline = Date.now() + delay;
		secondsUntilRefresh = Math.ceil(delay / 1000);
		countdownTimer = setInterval(() => {
			secondsUntilRefresh = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
		}, 250);
		timer = setTimeout(refresh, delay);
	}

	async function refresh() {
		stop();
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

{#if showStatus && pending && (inFlight || secondsUntilRefresh !== null)}
	<div
		class="mx-auto flex w-fit items-center gap-1.5 rounded-full bg-gray-50 px-3 py-1 text-xs text-gray-500"
		aria-busy={inFlight}
	>
		<RefreshOutline class={`h-3 w-3 ${inFlight ? 'motion-safe:animate-spin' : ''}`} />
		<span class="tabular-nums"
			>{inFlight ? 'Refreshing status…' : `Refresh in ${secondsUntilRefresh}s`}</span
		>
	</div>
{/if}
