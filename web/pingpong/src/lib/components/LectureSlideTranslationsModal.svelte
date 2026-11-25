<script lang="ts">
	import { onDestroy } from 'svelte';
	import { Button, Checkbox, Heading, Modal } from 'flowbite-svelte';
	import * as api from '$lib/api';
	import { sadToast } from '$lib/toast';

	let {
		open = $bindable(false),
		classId,
		assistantId,
		assistantName,
		deckReady,
		disabled = false
	}: {
		open?: boolean;
		classId: number;
		assistantId: number;
		assistantName: string;
		deckReady: boolean;
		disabled?: boolean;
	} = $props();

	const POLL_MS = 5000;

	let languages: api.LectureSlideLanguage[] = $state([]);
	let canPrepare = $state(false);
	let loaded = $state(false);
	let loadFailed = $state(false);
	let statuses: Record<string, api.LectureSlideTranslationStatusResponse> = $state({});
	let selected: string[] = $state([]);
	let preparing = $state(false);
	let pollTimer: ReturnType<typeof setTimeout> | null = null;
	let generation = 0;

	const translatable = $derived(languages.filter((language) => language.code !== 'original'));

	function isPreparing(code: string) {
		const status = statuses[code]?.status;
		return status === 'queued' || status === 'processing';
	}

	function canSelect(code: string) {
		const status = statuses[code]?.status ?? 'not_started';
		return status === 'not_started' || status === 'failed';
	}

	function statusLabel(code: string): string {
		const status = statuses[code];
		if (!status) return 'Not translated';
		switch (status.status) {
			case 'ready':
				return 'Ready';
			case 'queued':
				return 'Queued';
			case 'processing':
				return `Preparing ${status.completed_parts}/${status.total_parts}`;
			case 'failed':
				return 'Failed';
			default:
				return 'Needs update';
		}
	}

	function stopPolling() {
		if (pollTimer) clearTimeout(pollTimer);
		pollTimer = null;
	}

	function setStatuses(translations: api.LectureSlideTranslationStatusResponse[]) {
		statuses = {
			...statuses,
			...Object.fromEntries(
				translations.map((translation) => [translation.language_code, translation])
			)
		};
	}

	async function loadStatuses(current: number) {
		const expanded = await api
			.listLectureSlideTranslations(fetch, classId, assistantId)
			.then(api.expandResponse)
			.catch(() => null);
		if (current !== generation) return;
		stopPolling();
		if (expanded && !expanded.error) setStatuses(expanded.data.translations);
		if (!expanded || expanded.error || Object.keys(statuses).some(isPreparing)) {
			pollTimer = setTimeout(() => void loadStatuses(current), POLL_MS);
		}
	}

	async function load(current: number) {
		loaded = false;
		loadFailed = false;
		statuses = {};
		const expanded = await api
			.getLectureSlideLanguages(fetch, classId, assistantId)
			.then(api.expandResponse)
			.catch(() => null);
		if (current !== generation) return;
		if (!expanded || expanded.error) {
			loadFailed = true;
		} else {
			languages = expanded.data.languages;
			canPrepare = expanded.data.can_prepare;
			if (canPrepare && deckReady) await loadStatuses(current);
		}
		if (current === generation) loaded = true;
	}

	async function prepareSelected() {
		const current = generation;
		preparing = true;
		try {
			const expanded = api.expandResponse(
				await api.prepareLectureSlideTranslations(fetch, classId, assistantId, selected)
			);
			if (current !== generation) return;
			if (expanded.error) {
				sadToast(`Could not prepare translations: ${expanded.error.detail || 'Unknown error'}`);
				return;
			}
			setStatuses(expanded.data.translations);
			selected = [];
		} finally {
			preparing = false;
		}
		await loadStatuses(current);
	}

	$effect(() => {
		const current = ++generation;
		if (open) {
			void load(current);
		} else {
			stopPolling();
			selected = [];
		}
	});

	onDestroy(stopPolling);
</script>

<Modal bind:open size="md" outsideclose>
	<Heading tag="h3" class="font-serif text-2xl font-medium text-blue-dark-40">Translations</Heading>
	<p class="text-sm text-gray-600">
		Prepare translated narration for <b>{assistantName}</b> so students can choose a lesson language.
	</p>
	{#if !loaded}
		<p class="text-sm text-gray-500">Loading…</p>
	{:else if loadFailed}
		<p class="text-sm text-gray-600">Couldn't load translations. Try again.</p>
	{:else if !deckReady}
		<p class="text-sm text-gray-600">You can prepare translations once the lesson is ready.</p>
	{:else if !canPrepare}
		<p class="text-sm text-gray-600">You don't have permission to prepare translations.</p>
	{:else}
		<ul class="max-h-96 divide-y divide-gray-100 overflow-y-auto rounded-lg border border-gray-200">
			{#each translatable as language (language.code)}
				<li class="flex items-center justify-between gap-3 px-4 py-2">
					<Checkbox
						class="text-sm font-medium text-gray-900"
						value={language.code}
						bind:group={selected}
						disabled={disabled || preparing || !canSelect(language.code)}
					>
						{language.name}
					</Checkbox>
					<span
						class="shrink-0 text-xs {statuses[language.code]?.status === 'failed'
							? 'text-red-600'
							: statuses[language.code]?.status === 'ready'
								? 'text-green-700'
								: 'text-gray-500'}"
						title={statuses[language.code]?.error_message ?? undefined}
						>{statusLabel(language.code)}</span
					>
				</li>
			{/each}
		</ul>
		<div class="flex justify-end gap-3">
			<Button color="light" onclick={() => (open = false)}>Close</Button>
			<Button
				color="blue"
				disabled={disabled || preparing || selected.length === 0}
				onclick={prepareSelected}
			>
				{preparing
					? 'Preparing…'
					: selected.length === 1
						? 'Prepare 1 language'
						: `Prepare ${selected.length} languages`}
			</Button>
		</div>
	{/if}
</Modal>
