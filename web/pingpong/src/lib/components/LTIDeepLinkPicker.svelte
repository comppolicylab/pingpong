<script lang="ts">
	import { Button, Toggle, Tooltip } from 'flowbite-svelte';
	import {
		AnnotationOutline,
		BadgeCheckOutline,
		BookOpenOutline,
		ClapperboardPlayOutline,
		CloseOutline,
		ExclamationCircleOutline,
		MicrophoneOutline,
		SearchOutline,
		UsersGroupOutline
	} from 'flowbite-svelte-icons';
	import AssistantAvatar from '$lib/components/AssistantAvatar.svelte';
	import type * as api from '$lib/api';
	import {
		DEEP_LINK_SUBTITLE,
		DEEP_LINK_TITLE,
		ambiguousAssistantIds,
		assistantUpdatedLabel,
		filterDeepLinkAssistants,
		interactionModeLabel
	} from '$lib/ltiDeepLink';

	export let context: api.LTIDeepLinkContext;
	export let busy = false;
	export let errorMessage = '';
	export let onSubmit: (
		destination: api.LTIDeepLinkDestination,
		assistantId: number | null,
		simpleView: boolean
	) => void = () => {};
	export let onCancel: () => void = () => {};

	// One radio group for the group option and every assistant, so arrow keys walk
	// the whole list and the value carries both halves of the choice.
	let selection = 'group';
	let search = '';
	let searchInput: HTMLInputElement | null = null;
	// Applies to whichever assistant is selected, and is kept while the control is
	// disabled so switching to the group option and back does not lose it. Only
	// ever submitted alongside an assistant.
	let simpleView = false;

	const modeIcons = {
		chat: AnnotationOutline,
		voice: MicrophoneOutline,
		lecture_video: ClapperboardPlayOutline,
		lecture_slides: BookOpenOutline
	} as const;

	const rowClass = (selected: boolean) =>
		`flex gap-3 rounded-xl border p-3 transition-colors select-none focus-within:ring-3 focus-within:ring-orange/40 ${
			selected
				? 'border-orange bg-orange-light'
				: 'border-gray-200 bg-white hover:border-melon hover:bg-orange-light/60'
		}`;

	const simpleViewLabelClass = (eligible: boolean) =>
		eligible
			? 'text-xs whitespace-nowrap text-gray-800 contrast-100 grayscale-0'
			: 'text-xs whitespace-nowrap text-gray-400 contrast-50 grayscale';

	const clearSearch = () => {
		search = '';
		searchInput?.focus();
	};

	const updateSearch = (event: Event) => {
		const nextSearch = (event.currentTarget as HTMLInputElement).value;
		search = nextSearch;
		if (
			selectedAssistantId !== null &&
			!filterDeepLinkAssistants(assistants, nextSearch).some((a) => a.id === selectedAssistantId)
		) {
			selection = 'group';
		}
	};

	$: assistants = context.assistants;
	$: ambiguous = ambiguousAssistantIds(assistants);
	$: filtered = filterDeepLinkAssistants(assistants, search);
	$: selectedAssistantId = selection.startsWith('assistant:')
		? Number(selection.slice('assistant:'.length))
		: null;
	$: selectedAssistant = assistants.find((a) => a.id === selectedAssistantId) || null;
	let destination: api.LTIDeepLinkDestination = 'group';
	$: destination = selectedAssistant ? 'assistant' : 'group';
	$: simpleViewEligible = selectedAssistant !== null;
	$: showSearch = assistants.length > 4;
	$: trimmedSearch = search.trim();
</script>

<div class="flex min-h-0 flex-1 flex-col">
	<div class="flex shrink-0 flex-col gap-4 px-6 pt-6 md:px-10 lti-compact:gap-3 lti-compact:pt-4">
		<div class="lti-compact:hidden">
			<h2 class="text-2xl font-medium text-blue-dark-50">{DEEP_LINK_TITLE}</h2>
			<p class="mt-1 text-gray-600">{DEEP_LINK_SUBTITLE}</p>
		</div>

		<label class="block cursor-pointer rounded-xl focus-within:ring-3 focus-within:ring-orange/40">
			<input
				type="radio"
				name="lti-destination"
				class="sr-only"
				value="group"
				bind:group={selection}
			/>
			<div class={rowClass(!selectedAssistant)}>
				<span
					class="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-blue-light-40 text-blue-dark-40"
				>
					<UsersGroupOutline class="h-5 w-5" />
				</span>
				<div class="min-w-0 flex-1">
					<div class="font-semibold text-blue-dark-50">Show the Group's page</div>
					<p class="mt-0.5 text-sm text-gray-600">
						Students will land on the Group's page and can choose an assistant to chat with.
					</p>
				</div>
			</div>
		</label>

		{#if assistants.length > 0}
			<div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
				<span class="text-sm font-semibold tracking-wide text-gray-500 uppercase">
					Or link directly to an assistant
				</span>
				<Toggle
					size="small"
					color="blue"
					bind:checked={simpleView}
					disabled={!simpleViewEligible}
					classDiv="me-0"
					class={simpleViewLabelClass(simpleViewEligible)}
				>
					<span slot="offLabel">Show simple view</span>
				</Toggle>
				<Tooltip class="max-w-60 text-xs">
					{#if simpleViewEligible}
						Opens the assistant on its own in Canvas, without PingPong's navigation around it.
					{:else}
						Pick an assistant below to open it on its own in Canvas.
					{/if}
				</Tooltip>
			</div>

			{#if showSearch}
				<div class="relative">
					<SearchOutline
						class="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-gray-400"
					/>
					<input
						bind:this={searchInput}
						value={search}
						oninput={updateSearch}
						type="search"
						class="w-full rounded-xl border-gray-300 py-2.5 pl-9 text-sm placeholder-gray-400 focus:border-orange focus:ring-orange"
						placeholder="Search by name, description, creator, or type"
						aria-label="Search assistants"
					/>
					{#if trimmedSearch}
						<button
							type="button"
							class="absolute top-1/2 right-2 -translate-y-1/2 rounded-full p-1.5 text-gray-500 transition-colors hover:bg-gray-100"
							onclick={clearSearch}
							aria-label="Clear search"
						>
							<CloseOutline class="h-4 w-4" />
						</button>
					{/if}
				</div>
			{/if}
		{/if}
	</div>

	{#if assistants.length > 0}
		<div class="min-h-32 flex-1 overflow-y-auto px-6 pt-3 pb-4 md:px-10">
			<div class="flex flex-col gap-2">
				{#each filtered as assistant (assistant.id)}
					{@const selected = selectedAssistantId === assistant.id}
					{@const updated = assistantUpdatedLabel(assistant.updated)}
					{@const ModeIcon = modeIcons[assistant.interaction_mode]}
					<div class={rowClass(selected)}>
						<label class="flex min-w-0 flex-1 cursor-pointer gap-3">
							<input
								type="radio"
								name="lti-destination"
								class="sr-only"
								value={`assistant:${assistant.id}`}
								bind:group={selection}
							/>
							<AssistantAvatar {assistant} size={10} showFallback />
							<div class="min-w-0 flex-1">
								<div class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
									<span class="truncate font-semibold text-blue-dark-50">{assistant.name}</span>
									{#if ambiguous.has(assistant.id)}
										<span class="shrink-0 text-xs text-gray-400">#{assistant.id}</span>
									{/if}
									{#if assistant.endorsed}
										<span
											class="flex shrink-0 items-center gap-1 rounded-full bg-blue-light-40 px-2 py-0.5 text-xs font-medium text-blue-dark-50"
										>
											<BadgeCheckOutline class="h-3 w-3" />
											Group
										</span>
									{/if}
								</div>
								{#if assistant.description}
									<p class="mt-0.5 line-clamp-2 text-sm text-gray-600">
										{assistant.description}
									</p>
								{/if}
								<p class="mt-1 flex flex-wrap items-center gap-x-1.5 text-xs text-gray-500">
									<span class="flex shrink-0 items-center gap-1">
										<ModeIcon class="h-3.5 w-3.5" />
										{interactionModeLabel(assistant.interaction_mode)}
									</span>
									<span aria-hidden="true">&middot;</span>
									<span class="truncate">{assistant.creator_name}</span>
									{#if updated}
										<span aria-hidden="true">&middot;</span>
										<span>{updated}</span>
									{/if}
								</p>
							</div>
						</label>
					</div>
				{:else}
					<div class="rounded-xl bg-gray-50 p-6 text-center">
						<p class="text-sm text-gray-600">No assistants match “{trimmedSearch}”.</p>
						<button
							type="button"
							class="mt-2 text-sm font-semibold text-blue-dark-40 underline"
							onclick={clearSearch}
						>
							Clear search
						</button>
					</div>
				{/each}
			</div>
		</div>
	{:else}
		<div class="shrink-0 px-6 pt-4 md:px-10">
			<div class="rounded-xl bg-gray-50 p-4 text-sm text-gray-600">
				{context.group_name} has no published assistants yet. Link the whole group now — new assistants
				show up automatically.
			</div>
		</div>
	{/if}

	<div class="shrink-0 border-t border-gray-200 px-6 py-4 md:px-10 lti-compact:py-2">
		{#if errorMessage}
			<div
				class="mb-3 flex items-start gap-2 rounded-xl bg-red-light-50 p-3 text-sm text-red-700 lti-compact:mb-2 lti-compact:p-2 lti-compact:text-xs"
				role="alert"
			>
				<ExclamationCircleOutline class="mt-0.5 h-4 w-4 shrink-0" />
				<span>{errorMessage}</span>
			</div>
		{/if}
		<div class="flex flex-wrap items-center justify-between gap-3 lti-compact:gap-2">
			<p class="min-w-0 text-sm text-gray-500 lti-compact:text-xs" aria-live="polite">
				PingPong will show
				<span class="font-semibold text-blue-dark-50">
					{selectedAssistant ? selectedAssistant.name : "the Group's page"}
				</span>
				{#if selectedAssistant && simpleView}
					<span>on its own</span>
				{/if}
			</p>
			<div class="flex shrink-0 gap-3 lti-compact:gap-2">
				<Button
					class="rounded-full lti-compact:px-3 lti-compact:py-1.5 lti-compact:text-xs"
					color="alternative"
					disabled={busy}
					onclick={() => onCancel()}
				>
					Cancel
				</Button>
				<Button
					class="rounded-full bg-orange text-white hover:bg-orange-dark lti-compact:px-3 lti-compact:py-1.5 lti-compact:text-xs"
					disabled={busy}
					onclick={() => onSubmit(destination, selectedAssistantId, simpleView)}
				>
					{busy ? 'Adding...' : 'Add to Canvas'}
				</Button>
			</div>
		</div>
	</div>
</div>
