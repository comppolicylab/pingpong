<script lang="ts">
	import { resolve } from '$app/paths';
	import type { Assistant } from '$lib/api';
	import ViewAssistant from '$lib/components/ViewAssistant.svelte';
	import {
		Heading,
		Button,
		Input,
		Label,
		Modal,
		Select,
		Table,
		TableBody,
		TableBodyCell,
		TableBodyRow,
		TableHead,
		TableHeadCell
	} from 'flowbite-svelte';
	import {
		ArrowRightOutline,
		CirclePlusSolid,
		LinkOutline,
		PenSolid,
		FileCopyOutline,
		TrashBinOutline,
		CheckCircleOutline,
		ExclamationCircleOutline,
		InfoCircleOutline,

		TailwindSolid

	} from 'flowbite-svelte-icons';
	import ConfirmationModal from '$lib/components/ConfirmationModal.svelte';
	import { happyToast, sadToast } from '$lib/toast';
	import { copy } from 'svelte-copy';
	import { loading, loadingMessage } from '$lib/stores/general';
	import { invalidateAll } from '$app/navigation';
	import {
		checkCopyPermission as sharedCheckCopyPermission,
		defaultCopyName,
		parseTargetClassId,
		performCopyAssistant,
		performDeleteAssistant
	} from '$lib/assistantHelpers';

	export let data;

	$: hasApiKey = !!data?.hasAPIKey;
	$: creators = data?.assistantCreators || {};
	$: moderators = data?.supervisors || [];
	// "Course" assistants are endorsed by the class. Right now this means
	// they are created by the teaching team and are published.
	let courseAssistants: Assistant[] = [];
	// "My" assistants are assistants created by the current user, except
	// for those that appear in "course" assistants.
	let myAssistants: Assistant[] = [];
	// "Other" assistants are non-endorsed assistants that are not created by the current user.
	// For most people this means published assistants from other students. For people with
	// elevated permissions, this could also mean private assistants.
	let otherAssistants: Assistant[] = [];
	let copyModalState: Record<number, boolean> = {};
	let deleteModalState: Record<number, boolean> = {};
	let copyNames: Record<number, string> = {};
	let copyTargets: Record<number, string> = {};
	let copyPermissionAllowed: Record<number, boolean> = {};
	let copyPermissionLoading: Record<number, boolean> = {};
	let copyPermissionError: Record<number, string> = {};
	const baseUrl = typeof window !== 'undefined' ? window.location.origin : '';
	const classOptions = (data.classes || []).map((c) => ({
		id: c.id,
		name: c.name,
		term: c.term
	}));
	const assistantLink = (assistantId: number) =>
		`${baseUrl}/group/${data.class.id}?assistant=${assistantId}`;

	const openCopyModal = (assistantId: number, name: string) => {
		copyModalState = { ...copyModalState, [assistantId]: true };
		copyNames = { ...copyNames, [assistantId]: defaultCopyName(name) };
		copyTargets = { ...copyTargets, [assistantId]: `${data.class.id}` };
		copyPermissionAllowed = { ...copyPermissionAllowed, [assistantId]: true };
		copyPermissionLoading = { ...copyPermissionLoading, [assistantId]: false };
		copyPermissionError = { ...copyPermissionError, [assistantId]: '' };
		void checkCopyPermission(assistantId, `${data.class.id}`);
	};

	const closeCopyModal = (assistantId: number) => {
		copyModalState = { ...copyModalState, [assistantId]: false };
	};

	const openDeleteModal = (assistantId: number) => {
		deleteModalState = { ...deleteModalState, [assistantId]: true };
	};

	const closeDeleteModal = (assistantId: number) => {
		deleteModalState = { ...deleteModalState, [assistantId]: false };
	};

	const handleCopyAssistant = async (assistantId: number) => {
		if (copyPermissionLoading[assistantId]) {
			return sadToast('Please wait while we check permissions.');
		}
		if (copyPermissionAllowed[assistantId] !== true) {
			return sadToast(
				copyPermissionError[assistantId] || "You don't have permission to copy to that group."
			);
		}
		const fallbackName =
			otherAssistants.find((a) => a.id === assistantId)?.name ||
			courseAssistants.find((a) => a.id === assistantId)?.name ||
			myAssistants.find((a) => a.id === assistantId)?.name ||
			'Assistant';
		const name = (copyNames[assistantId] || '').trim() || defaultCopyName(fallbackName);
		$loadingMessage = 'Copying assistant...';
		$loading = true;
		const result = await performCopyAssistant(fetch, data.class.id, assistantId, {
			name,
			fallbackName: fallbackName,
			targetClassId: copyTargets[assistantId]
		});
		if (result.error) {
			$loadingMessage = '';
			$loading = false;
			const detail =
				(result.error as Error & { detail?: string }).detail ||
				(result.error as Error).message ||
				'Unknown error';
			return sadToast(`Failed to copy assistant: ${detail}`);
		}
		happyToast('Assistant copied', 2000);
		await invalidateAll();
		$loadingMessage = '';
		$loading = false;
		closeCopyModal(assistantId);
	};

	const handleDeleteAssistant = async (assistantId: number) => {
		closeDeleteModal(assistantId);
		$loadingMessage = 'Deleting assistant...';
		$loading = true;
		const result = await performDeleteAssistant(fetch, data.class.id, assistantId);
		if (result.error) {
			$loadingMessage = '';
			$loading = false;
			const detail =
				(result.error as Error & { detail?: string }).detail ||
				(result.error as Error).message ||
				'Unknown error';
			return sadToast(`Error deleting assistant: ${detail}`);
		}
		happyToast('Assistant deleted');
		await invalidateAll();
		$loadingMessage = '';
		$loading = false;
	};

	const showCopiedLink = (e: Event) => {
		e.preventDefault();
		e.stopPropagation();
		happyToast('Link copied to clipboard', 2000);
	};

	const updateCopyName = (assistantId: number, value: string) => {
		copyNames = { ...copyNames, [assistantId]: value };
	};

	const handleCopyNameInput = (assistantId: number, event: Event) => {
		const target = event.target as HTMLInputElement;
		updateCopyName(assistantId, target?.value || '');
	};

	const updateCopyTarget = (assistantId: number, value: string) => {
		copyTargets = { ...copyTargets, [assistantId]: value };
	};

	const checkCopyPermission = async (assistantId: number, targetClassId: string) => {
		const targetId = parseTargetClassId(targetClassId, data.class.id);
		if (targetId === null) {
			copyPermissionAllowed = { ...copyPermissionAllowed, [assistantId]: false };
			copyPermissionError = { ...copyPermissionError, [assistantId]: 'Invalid class selected.' };
			return;
		}
		copyPermissionLoading = { ...copyPermissionLoading, [assistantId]: true };
		copyPermissionError = { ...copyPermissionError, [assistantId]: '' };
		const result = await sharedCheckCopyPermission(fetch, data.class.id, assistantId, targetId);
		copyPermissionAllowed = { ...copyPermissionAllowed, [assistantId]: result.allowed };
		copyPermissionError = { ...copyPermissionError, [assistantId]: result.error };
		copyPermissionLoading = { ...copyPermissionLoading, [assistantId]: false };
	};

	const handleCopyTargetSelect = (assistantId: number, event: Event) => {
		const target = event.target as HTMLSelectElement;
		const value = target?.value || '';
		updateCopyTarget(assistantId, value);
		void checkCopyPermission(assistantId, value);
	};
	$: {
		const allAssistants = data?.assistants || [];
		// Split all assistants into categories
		courseAssistants = allAssistants.filter((assistant) => assistant.endorsed);
		myAssistants = allAssistants.filter(
			(assistant) => assistant.creator_id === data.me.user!.id && !assistant.endorsed
		);
		otherAssistants = allAssistants.filter(
			(assistant) => assistant.creator_id !== data.me.user!.id && !assistant.endorsed
		);
	}
</script>

<div class="h-full w-full overflow-y-auto p-12">
	{#if !hasApiKey}
		<Heading tag="h2" class="text-dark-blue-40 mb-4 font-serif text-3xl font-medium"
			>No API key.</Heading
		>
		<div>You must configure an API key for this group before you can create or use assistants.</div>
	{:else}
		{#if data.grants.canCreateAssistants}
			<Heading tag="h2" class="text-dark-blue-40 mb-4 font-serif text-3xl font-medium"
				>Make a new assistant</Heading
			>
			<div class="mb-12 items-start justify-between gap-12 rounded-2xl bg-gold p-8 lg:flex">
				<p class="font-light">
					Build your own AI chatbot for this group. You can customize it with specific knowledge,
					personality, and parameters to serve as a digital assistant for this group.
				</p>
				<a
					href={resolve(`/group/${data.class.id}/assistant/new`)}
					class="hover:text-blue-dark-100 flex shrink-0 items-center justify-center rounded-full bg-white p-2 px-4 text-sm font-medium text-blue-dark-50 transition-all hover:bg-blue-dark-40 hover:text-white"
					>Create new assistant <ArrowRightOutline size="md" class="orange inline-block" /></a
				>
			</div>
		{/if}

		<Heading tag="h2" class="text-dark-blue-40 mb-4 font-serif text-3xl font-medium"
			>Your assistants</Heading
		>
		<div class="mb-12 grid gap-4 md:grid-cols-2">
			{#each myAssistants as assistant (assistant.id)}
				<ViewAssistant
					{assistant}
					creator={creators[assistant.creator_id]}
					editable={data.editableAssistants.has(assistant.id)}
					currentClassId={data.class.id}
					{classOptions}
				/>
			{:else}
				<div>No assistants</div>
			{/each}
		</div>

		<Heading tag="h2" class="text-dark-blue-40 mb-4 font-serif text-3xl font-medium"
			>Group assistants</Heading
		>
		<div class="mb-12 grid gap-4 md:grid-cols-2">
			{#each courseAssistants as assistant (assistant.id)}
				<ViewAssistant
					{assistant}
					creator={creators[assistant.creator_id]}
					editable={data.editableAssistants.has(assistant.id)}
					shareable={data.grants.canShareAssistants && !!assistant.published}
					currentClassId={data.class.id}
					{classOptions}
				/>
			{:else}
				<div>No group assistants</div>
			{/each}
		</div>

		<Heading tag="h2" class="text-dark-blue-40 mb-4 font-serif text-3xl font-medium"
			>Other assistants</Heading
		>
		{#if otherAssistants.length === 0}
			<div>No other assistants</div>
		{:else}
			<Table>
				<TableHead class="rounded-2xl bg-blue-light-40 p-1 tracking-wide text-blue-dark-50">
					<TableHeadCell>Assistant Name</TableHeadCell>
					<TableHeadCell>Author</TableHeadCell>
					<TableHeadCell>Status</TableHeadCell>
					<TableHeadCell>Chat</TableHeadCell>
					<TableHeadCell class="text-right">Actions</TableHeadCell>
				</TableHead>
				<TableBody>
					{#each otherAssistants as assistant (assistant.id)}
						<TableBodyRow>
							<TableBodyCell class="font-light">{assistant.name}</TableBodyCell>
							<TableBodyCell class="font-light"
								>{creators[assistant.creator_id]?.name || 'unknown'}</TableBodyCell
							>
							<TableBodyCell class="font-light"
								>{assistant.published ? 'Published' : 'Private'}</TableBodyCell
							>
							<TableBodyCell
								><a
									href={resolve(`/group/${data.class.id}?assistant=${assistant.id}`)}
									class="hover:text-blue-dark-100 flex w-32 items-center gap-2 rounded-full bg-orange p-1 px-3 text-sm font-medium text-white transition-all hover:bg-blue-dark-40 hover:text-white"
									>Start a chat <CirclePlusSolid size="sm" class="inline" /></a
								></TableBodyCell
							>
							<TableBodyCell>
								<div class="flex flex-wrap justify-end gap-2">
									<button
										class="hover:text-blue-dark-100 text-blue-dark-40"
										aria-label="Copy assistant link"
										onclick={() => {}}
										oncopy={showCopiedLink}
										use:copy={assistantLink(assistant.id)} 
									>
										<LinkOutline class="h-5 w-5" />
									</button>
									{#if data.editableAssistants.has(assistant.id)}
										<a
											href={resolve(`/group/${data.class.id}/assistant/${assistant.id}`)}
											class="hover:text-blue-dark-100 text-blue-dark-40"
											aria-label="Edit assistant"><PenSolid class="h-5 w-5" /></a
										>
										<button
											class="hover:text-blue-dark-100 text-blue-dark-40"
											aria-label="Copy assistant"
											onclick={(event) => {
												event.preventDefault();
												openCopyModal(assistant.id, assistant.name);
											}}
										>
											<FileCopyOutline class="h-5 w-5" />
										</button>
										<button
											class="text-red-700 hover:text-red-900"
											aria-label="Delete assistant"
											onclick={(event) => {
												event.preventDefault();
												openDeleteModal(assistant.id);
											}}
										>
											<TrashBinOutline class="h-5 w-5" />
										</button>
									{/if}
								</div>
								
								<Modal
									open={!!copyModalState[assistant.id]}
									size="md"
									onclose={() => closeCopyModal(assistant.id)}
								>
									<div class="text-left break-words whitespace-normal">
										<Heading tag="h3" class="font-serif text-2xl font-medium text-blue-dark-40"
											>Copy Assistant</Heading
										>
										<p class="mt-3 mb-4 break-words whitespace-normal text-blue-dark-40">
											This will create a private copy of <b>{assistant.name}</b> in the group you select.
											You can rename it below.
										</p>
										<div class="mb-6">
											<Label
												for={`copy-name-${assistant.id}`}
												class="mb-1 block text-sm font-medium text-blue-dark-50"
												>New Assistant Name</Label
											>
											<Input
												id={`copy-name-${assistant.id}`}
												name={`copy-name-${assistant.id}`}
												value={copyNames[assistant.id] || ''}
												oninput={(event) => handleCopyNameInput(assistant.id, event)}
												placeholder={defaultCopyName(assistant.name)}
											/>
										</div>
										<div class="mb-6">
											<div
												class="mt-2 mb-1 flex items-center justify-between text-sm text-blue-dark-50"
											>
												<Label
													for={`copy-target-${assistant.id}`}
													class="block text-sm font-medium text-blue-dark-50">Copy to...</Label
												>

												{#if copyPermissionLoading[assistant.id]}
													<span class="text-gray-500 italic">Checking permissions...</span>
												{:else if copyPermissionAllowed[assistant.id] ?? true}
													<span class="flex items-center gap-1 text-green-700">
														<CheckCircleOutline class="h-4 w-4" /> Can create assistant in this Group
													</span>
												{:else}
													<span class="flex items-center gap-1 text-red-700">
														<ExclamationCircleOutline class="h-4 w-4" />
														{copyPermissionError[assistant.id] ||
															"Can't create assistant in this Group"}
													</span>
												{/if}
											</div>

											<Select
												id={`copy-target-${assistant.id}`}
												name={`copy-target-${assistant.id}`}
												value={copyTargets[assistant.id] || ''}
												onchange={(event) => handleCopyTargetSelect(assistant.id, event)}
											>
												{#each classOptions as option (option.id)}
													<option value={`${option.id}`}>
														{option.term ? `${option.name} (${option.term})` : option.name}
													</option>
												{/each}
											</Select>
										</div>
										<div class="flex justify-end gap-3">
											<Button color="light" onclick={() => closeCopyModal(assistant.id)}
												>Cancel</Button
											>
											<Button
												color="blue"
												disabled={copyPermissionLoading[assistant.id] ||
													copyPermissionAllowed[assistant.id] !== true}
												onclick={() => handleCopyAssistant(assistant.id)}>Copy</Button
											>
										</div>
									</div>
								</Modal>

								<Modal
									open={!!deleteModalState[assistant.id]}
									size="xs"
									autoclose
									onclose={() => closeDeleteModal(assistant.id)}
								>
									<ConfirmationModal
										warningTitle={`Delete ${assistant?.name || 'this assistant'}?`}
										warningDescription="All threads associated with this assistant will become read-only."
										warningMessage="This action cannot be undone."
										cancelButtonText="Cancel"
										confirmText="delete"
										confirmButtonText="Delete assistant"
										on:cancel={() => closeDeleteModal(assistant.id)}
										on:confirm={() => handleDeleteAssistant(assistant.id)}
									/>
								</Modal>
							</TableBodyCell>
						</TableBodyRow>
					{/each}
				</TableBody>
			</Table>
		{/if}
	{/if}
	<Heading tag="h2" class="text-dark-blue-40 mt-12 mb-4 font-serif text-3xl font-medium"
		>Group Moderators</Heading
	>
	{#if moderators.length === 0}
		<div>No supervisors</div>
	{:else}
		<Table>
			<TableHead class="rounded-2xl bg-blue-light-40 p-1 tracking-wide text-blue-dark-50">
				<TableHeadCell>Moderator Name</TableHeadCell>
				<TableHeadCell>Email</TableHeadCell>
			</TableHead>
			<TableBody>
				{#each moderators as moderator (moderator.email)}
					<TableBodyRow>
						{#if moderator.name}
							<TableBodyCell class="font-light">{moderator.name}</TableBodyCell>
						{:else}
							<TableBodyCell class="font-light italic">No recorded name</TableBodyCell>
						{/if}
						<TableBodyCell class="font-light">{moderator.email}</TableBodyCell>
					</TableBodyRow>
				{/each}
			</TableBody>
		</Table>
	{/if}
</div>
