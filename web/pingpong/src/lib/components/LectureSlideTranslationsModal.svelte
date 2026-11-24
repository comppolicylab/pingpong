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
	let statuses: Record<string, api.LectureSlideTranslationStatusResponse> = $state({});
	let selected: string[] = $state([]);
	let preparing = $state(false);
	let pollTimer: ReturnType<typeof setTimeout> | null = null;

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

	async function loadStatuses() {
		stopPolling();
		const expanded = api.expandResponse(
			await api.listLectureSlideTranslations(fetch, classId, assistantId)
		);
		if (expanded.error || !open) return;
		statuses = Object.fromEntries(
			expanded.data.translations.map((translation) => [translation.language_code, translation])
		);
		if (Object.keys(statuses).some(isPreparing)) {
			pollTimer = setTimeout(() => void loadStatuses(), POLL_MS);
		}
	}

	async function load() {
		loaded = false;
		const expanded = api.expandResponse(
			await api.getLectureSlideLanguages(fetch, classId, assistantId)
		);
		if (!expanded.error) {
			languages = expanded.data.languages;
			canPrepare = expanded.data.can_prepare;
			if (canPrepare && deckReady) await loadStatuses();
		}
		loaded = true;
	}

	async function prepareSelected() {
		preparing = true;
		const failures: string[] = [];
		try {
			for (const code of selected) {
				const expanded = api.expandResponse(
					await api.prepareLectureSlideTranslation(fetch, classId, assistantId, code)
				);
				if (expanded.error) {
					const name = languages.find((language) => language.code === code)?.name ?? code;
					failures.push(`${name}: ${expanded.error.detail || 'Unknown error'}`);
				} else {
					statuses = { ...statuses, [code]: expanded.data };
				}
			}
			selected = [];
		} finally {
			preparing = false;
		}
		if (failures.length > 0) {
			sadToast(`Could not prepare some translations:\n${failures.join('\n')}`);
		}
		await loadStatuses();
	}

	$effect(() => {
		if (open) {
			void load();
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
