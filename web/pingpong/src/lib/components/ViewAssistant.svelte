<script lang="ts">
	import { page } from '$app/stores';
	import { copy } from 'svelte-copy';
	import {
		Button,
		Heading,
		Label,
		Input,
		Modal,
		Table,
		TableBody,
		TableBodyCell,
		TableBodyRow,
		TableHead,
		TableHeadCell,
		Tooltip,
		Select
	} from 'flowbite-svelte';
	import {
		EyeOutline,
		EyeSlashOutline,
		LinkOutline,
		PenSolid,
		CirclePlusSolid,
		GlobeOutline,
		PlusOutline,
		FileCopyOutline,
		TrashBinOutline,
		CheckCircleOutline,
		ExclamationCircleOutline,
		InfoCircleOutline
	} from 'flowbite-svelte-icons';
	import ConfirmationModal from '$lib/components/ConfirmationModal.svelte';
	import type { Assistant, AppUser } from '$lib/api';
	import dayjs from 'dayjs';
	import { happyToast, sadToast } from '$lib/toast';
	import * as api from '$lib/api';
	import { resolve } from '$app/paths';
	import {
		checkCopyPermission as sharedCheckCopyPermission,
		defaultCopyName,
		parseTargetClassId,
		performCopyAssistant,
		performDeleteAssistant
	} from '$lib/assistantHelpers';
	import { invalidateAll } from '$app/navigation';
	import { loading, loadingMessage } from '$lib/stores/general';

	export let assistant: Assistant;
	export let creator: AppUser;
	export let editable = false;
	export let shareable = false;
	export let classOptions: { id: number; name: string; term: string }[] = [];
	export let currentClassId: number;

	let sharedAssistantModalOpen = false;
	let qualtricsCodeModalOpen = false;
	let copyAssistantModalOpen = false;
	let deleteAssistantModalOpen = false;
	let notesAssistantModalOpen = false;
	let qualtricsCodeLinkName = '';
	let qualtricsQuestionJavaScript = '';
	let qualtricsQuestionHTML = '';
	let copyName = '';
	let copyTargetClassId = `${currentClassId}`;
	let copyPermissionAllowed: boolean | undefined = undefined;
	let copyPermissionLoading = false;
	let copyPermissionError = '';

	// Get the full URL to use the assistant
	$: assistantLink = `${$page.url.protocol}//${$page.url.host}/group/${assistant.class_id}?assistant=${assistant.id}`;
	$: sharedAssistantLinkWithParam = `${$page.url.protocol}//${$page.url.host}/group/${assistant.class_id}/shared/assistant/${assistant.id}?share_token=`;

	$: currentlyShared = assistant.share_links?.some((link) => link.active);
	$: shareLinks = assistant.share_links || [];

	// Show info that we copied the link to the clipboard
	const showCopiedLink = () => {
		happyToast('Link copied to clipboard', 3000);
	};
	const showCopiedText = (label: string) => {
		happyToast(`${label} copied to clipboard`, 3000);
	};

	const buildQualtricsSnippets = (linkUrl: string) => {
		const questionJavaScript = `Qualtrics.SurveyEngine.addOnReady(function()
{
	var questionContainer = this.getQuestionContainer();
	if (!questionContainer) {
		return;
	}

	var conversationIdInput = questionContainer.querySelector('input[type="text"], textarea');
	if (!conversationIdInput) {
		return;
	}

	var existingConversationId = conversationIdInput.value ? conversationIdInput.value.trim() : '';
	var conversationId =
		existingConversationId ||
		String(Math.floor(Math.random() * 900000000000000) + 100000000000000);

	conversationIdInput.value = conversationId;
	conversationIdInput.dispatchEvent(new Event('input', { bubbles: true }));
	conversationIdInput.dispatchEvent(new Event('change', { bubbles: true }));
	conversationIdInput.style.display = 'none';

	var iframe = questionContainer.querySelector('#pingpong-anonymous-session-iframe');
	if (!iframe) {
		return;
	}

	var baseLink = iframe.getAttribute('data-base-src') || '';
	if (!baseLink) {
		return;
	}

	var separator = baseLink.indexOf('?') >= 0 ? '&' : '?';
	iframe.src = baseLink + separator + 'conversation_id=' + encodeURIComponent(conversationId);
});`;

		const questionHTML = `<iframe
	id="pingpong-anonymous-session-iframe"
	style="border:0"
	data-base-src="${linkUrl}"
	height="1000px"
	width="100%"
	allow="clipboard-write *; microphone *"
></iframe>`;

		return {
			questionJavaScript,
			questionHTML
		};
	};

	const openQualtricsCodeModal = (linkName: string | null | undefined, shareToken: string) => {
		const linkUrl = `${sharedAssistantLinkWithParam}${shareToken}`;
		const snippets = buildQualtricsSnippets(linkUrl);
		qualtricsCodeLinkName = linkName?.trim() || 'Shared Link';
		qualtricsQuestionJavaScript = snippets.questionJavaScript;
		qualtricsQuestionHTML = snippets.questionHTML;
		qualtricsCodeModalOpen = true;
	};

	const checkCopyPermission = async (targetClassId: string) => {
		const targetId = parseTargetClassId(targetClassId, currentClassId);
		if (targetId === null) {
			copyPermissionAllowed = false;
			copyPermissionError = 'Invalid class selected.';
			return;
		}
		copyPermissionLoading = true;
		copyPermissionError = '';
		const result = await sharedCheckCopyPermission(
			fetch,
			assistant.class_id,
			assistant.id,
			targetId
		);
		copyPermissionAllowed = result.allowed;
		copyPermissionError = result.error;
		copyPermissionLoading = false;
	};

	const createLink = async () => {
		const result = await api.createAssistantShareLink(fetch, assistant.class_id, assistant.id);
		const expanded = api.expandResponse(result);
		if (expanded.error) {
			return sadToast(`Failed to create shared link: ${expanded.error.detail}`);
		}

		happyToast('Shared link created successfully', 3000);
		await invalidateAll();
	};

	const submitInputForm = async (e: Event, link_id: number) => {
		e.preventDefault();
		e.stopPropagation();
		const target = e.target as HTMLInputElement;
		const name = target.value.trim();

		const result = await api.updateAssistantShareLinkName(
			fetch,
			assistant.class_id,
			assistant.id,
			link_id,
			{ name }
		);
		const expanded = api.expandResponse(result);
		if (expanded.error) {
			return sadToast(`Failed to update shared link: ${expanded.error.detail}`);
		}
		happyToast('Shared link updated successfully', 2000);
	};

	const deleteLink = async (link_id: number) => {
		const result = await api.deleteAssistantShareLink(
			fetch,
			assistant.class_id,
			assistant.id,
			link_id
		);
		const expanded = api.expandResponse(result);
		if (expanded.error) {
			return sadToast(`Failed to deactivate shared link: ${expanded.error.detail}`);
		}
		happyToast('Shared link deactivated successfully', 2000);
		await invalidateAll();
	};

	const copyAssistant = async () => {
		if (copyPermissionLoading) {
			return sadToast('Please wait while we check permissions.');
		}
		if (!copyPermissionAllowed) {
			return sadToast(copyPermissionError || "You don't have permission to copy to that group.");
		}
		$loadingMessage = 'Copying assistant...';
		$loading = true;
		const result = await performCopyAssistant(fetch, assistant.class_id, assistant.id, {
			name: copyName,
			fallbackName: assistant.name,
			targetClassId: copyTargetClassId
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
		copyAssistantModalOpen = false;
	};

	const deleteAssistant = async () => {
		deleteAssistantModalOpen = false;
		$loadingMessage = 'Deleting assistant...';
		$loading = true;
		const result = await performDeleteAssistant(fetch, assistant.class_id, assistant.id);
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
</script>

<Modal size="xl" bind:open={sharedAssistantModalOpen}>
	<slot name="header">
		<Heading
			tag="h2"
			class="mr-5 mb-4 max-w-max shrink-0 font-serif text-3xl font-medium text-blue-dark-40"
			color="blue">Manage Shared Links</Heading
		>
	</slot>
	<div class="mb-4 flex flex-row flex-wrap items-center justify-between gap-y-4 text-blue-dark-50">
		<Button
			pill
			size="sm"
			class="flex flex-row gap-2 border border-solid border-blue-dark-40 bg-white text-blue-dark-40 hover:bg-blue-dark-40 hover:text-white"
			onclick={createLink}><PlusOutline />New Shared Link</Button
		>
	</div>

	<div>
		<Table class="w-full">
			<TableHead class="rounded-2xl bg-blue-light-40 p-1 tracking-wide text-blue-dark-50">
				<TableHeadCell>Description</TableHeadCell>
				<TableHeadCell>Status</TableHeadCell>
				<TableHeadCell>Last Updated</TableHeadCell>
				<TableHeadCell></TableHeadCell>
			</TableHead>
			<TableBody>
				{#each shareLinks as link (link.id)}
					<TableBodyRow>
						<TableBodyCell class="py-2 font-medium whitespace-normal"
							><Input
								id="name"
								name="name"
								value={link.name}
								placeholder="Shared Link"
								onchange={(e) => submitInputForm(e, link.id)}
							/></TableBodyCell
						>
						<TableBodyCell
							class="py-2 text-sm font-normal font-semibold whitespace-normal uppercase {!link.active
								? 'text-gray-700'
								: 'text-green-700'}"
						>
							{link.active ? 'Active' : 'Inactive'}
						</TableBodyCell>
						<TableBodyCell class="py-2 font-normal whitespace-normal">
							{link.revoked_at
								? dayjs.utc(link.revoked_at).fromNow()
								: link.activated_at
									? dayjs.utc(link.activated_at).fromNow()
									: ''}
						</TableBodyCell>

						<TableBodyCell class="py-2">
							<div class="flex flex-row gap-2">
								<button
									class="flex w-fit shrink-0 flex-row items-center justify-center gap-1.5 rounded-full border border-blue-dark-40 bg-white p-1 px-3 text-xs text-blue-dark-40 transition-all hover:bg-blue-dark-40 hover:text-white"
									onclick={(event) => {
										event.preventDefault();
									}}
									use:copy={{
										text: `${sharedAssistantLinkWithParam}${link.share_token}`,
										onCopy: showCopiedLink
									}}
								>
									<LinkOutline class="inline-block h-4 w-4" />
									Copy Link
								</button>
								<Button
									pill
									size="sm"
									class="flex w-fit shrink-0 flex-row items-center justify-center gap-1.5 rounded-full border border-blue-dark-40 bg-white p-1 px-3 text-xs text-blue-dark-40 transition-all hover:bg-blue-dark-40 hover:text-white"
									disabled={!link.active}
									onclick={() => openQualtricsCodeModal(link.name, link.share_token)}
								>
									Qualtrics Instructions
								</Button>
								{#if link.active}
									<Button
										pill
										size="sm"
										class="flex w-fit shrink-0 flex-row items-center justify-center gap-1.5 rounded-full border border-gray-800 bg-white p-1 px-3 text-xs text-gray-800 transition-all hover:bg-gray-800 hover:text-white"
										disabled={!link.active}
										onclick={() => deleteLink(link.id)}
									>
										Disable Link
									</Button>
								{/if}
							</div>
						</TableBodyCell>
					</TableBodyRow>
				{/each}
			</TableBody>
		</Table>
	</div>
</Modal>

<Modal size="xl" bind:open={qualtricsCodeModalOpen}>
	<slot name="header">
		<Heading
			tag="h2"
			class="mr-5 mb-2 max-w-max shrink-0 font-serif text-3xl font-medium text-blue-dark-40"
			color="blue">Qualtrics Instructions</Heading
		>
	</slot>
	<p class="mb-2 text-sm text-blue-dark-50">
		Use the instructions below to embed <i
			>&ldquo;{assistant.name}&rdquo; ({qualtricsCodeLinkName})</i
		> in a Qualtrics survey. Each respondent will be assigned a random Conversation ID that can be used
		to match their conversation between PingPong thread exports and Qualtrics data exports.
	</p>
	<ol class="ml-5 list-decimal text-blue-dark-50">
		<li class="mb-2 text-sm text-blue-dark-50">
			Create a new Text Entry question in your Qualtrics survey. This question will be used to store
			the Conversation ID for each respondent.
		</li>
		<li class="mb-2 text-sm text-blue-dark-50">
			On the left side of the question editing pane, click on the &ldquo;JavaScript&rdquo; option.
			This will open a code editor where you can add custom JavaScript for this question. Copy the
			JavaScript code from the &ldquo;Question JavaScript&rdquo; block below and <b>replace</b> the
			placeholder code in the editor, then save your changes.
			<div class="mt-2 mb-5 rounded-xl border border-blue-light-30 bg-white p-4">
				<div class="mb-2 flex items-center justify-between gap-2">
					<Heading tag="h3" class="text-lg font-medium text-blue-dark-40"
						>Question JavaScript</Heading
					>
					<button
						class="rounded-full border border-blue-dark-40 bg-white px-3 py-1 text-xs text-blue-dark-40 transition-all hover:bg-blue-dark-40 hover:text-white"
						onclick={(event) => {
							event.preventDefault();
						}}
						use:copy={{
							text: qualtricsQuestionJavaScript,
							onCopy: () => showCopiedText('Question JavaScript')
						}}
					>
						Copy
					</button>
				</div>
				<pre
					class="max-h-72 overflow-auto rounded-lg bg-gray-50 p-3 font-mono text-xs leading-5 whitespace-pre text-gray-800">{qualtricsQuestionJavaScript}</pre>
			</div>
		</li>
		<li class="mb-2 text-sm text-blue-dark-50">
			Click on the placeholder text in your Text Entry question and select &ldquo;HTML View&rdquo;
			on the top right. This will open a text editor where you can add custom HTML for this
			question. Copy the HTML code from the &ldquo;Question HTML&rdquo; block below and <b
				>replace</b
			>
			the placeholder content in the editor, then save your changes. You can change the
			<span class="font-mono">height="1000px"</span>
			attribute in the HTML code if you want to adjust the height of the assistant iframe in your survey.
			<div class="mt-2 mb-3 rounded-xl border border-blue-light-30 bg-white p-4">
				<div class="mb-2 flex items-center justify-between gap-2">
					<Heading tag="h3" class="text-lg font-medium text-blue-dark-40"
						>Question HTML View</Heading
					>
					<button
						class="rounded-full border border-blue-dark-40 bg-white px-3 py-1 text-xs text-blue-dark-40 transition-all hover:bg-blue-dark-40 hover:text-white"
						onclick={(event) => {
							event.preventDefault();
						}}
						use:copy={{
							text: qualtricsQuestionHTML,
							onCopy: () => showCopiedText('Question HTML')
						}}
					>
						Copy
					</button>
				</div>
				<pre
					class="max-h-56 overflow-auto rounded-lg bg-gray-50 p-3 font-mono text-xs leading-5 whitespace-pre text-gray-800">{qualtricsQuestionHTML}</pre>
			</div>
		</li>
		<li class="mb-2 text-sm text-blue-dark-50">
			Done! When respondents take your survey, the assistant will appear embedded in this question.
			The Text Entry question will be hidden from respondents, but it will store a unique
			Conversation ID for each respondent that is used to track their conversation in PingPong.
		</li>
	</ol>
</Modal>

<div
	class="flex flex-col gap-2 {editable
		? 'bg-gold-light'
		: 'bg-orange-light'} rounded-2xl px-8 py-4 pt-6 pb-8"
>
	<Heading
		tag="h3"
		class="flex flex-wrap items-center justify-between gap-x-4 gap-y-0 text-3xl font-normal"
	>
		<div class="min-w-0">
			<span class="mr-2 break-words">{assistant.name}</span>
			<span class="inline-flex flex-wrap items-center gap-1 align-baseline">
				{#if !assistant.published}
					<EyeSlashOutline class="mr-1 inline-block h-5 w-5 text-gray-500" />
					<Tooltip placement="top" class="text-xs font-light"
						>This assistant is not currently published.</Tooltip
					>
				{:else}
					<EyeOutline class="mr-1 inline-block h-5 w-5 text-orange" />
					<Tooltip placement="top" class="text-xs font-light"
						>This assistant is currently published and available to all members.</Tooltip
					>
				{/if}
				{#if currentlyShared}
					<GlobeOutline class="mr-1 inline-block h-5 w-5 text-orange" />
					<Tooltip placement="top" class="text-xs font-light"
						>One or more sharable links are active for this assistant.</Tooltip
					>
				{/if}
			</span>
		</div>

		<div class="flex shrink-0 items-center gap-2">
			{#if editable}
				{#if assistant.notes}
					<button
						class="text-blue-dark-30 hover:text-blue-dark-50"
						aria-label="Assistant notes"
						onclick={(event) => {
							event.preventDefault();
							notesAssistantModalOpen = true;
						}}><InfoCircleOutline side="md" /></button
					>
				{/if}
				<button
					class="text-blue-dark-30 hover:text-blue-dark-50"
					aria-label="Copy assistant"
					onclick={(event) => {
						event.preventDefault();
						copyName = defaultCopyName(assistant.name);
						copyTargetClassId = `${currentClassId}`;
						copyPermissionAllowed = false;
						copyPermissionLoading = false;
						copyPermissionError = '';
						checkCopyPermission(copyTargetClassId);
						copyAssistantModalOpen = true;
					}}><FileCopyOutline size="md" /></button
				>
				<button
					class="text-blue-dark-30 hover:text-blue-dark-50"
					aria-label="Delete assistant"
					onclick={(event) => {
						event.preventDefault();
						deleteAssistantModalOpen = true;
					}}><TrashBinOutline size="md" /></button
				>
				<a
					class="text-blue-dark-30 hover:text-blue-dark-50"
					href={resolve(`/group/${assistant.class_id}/assistant/${assistant.id}`)}
					><PenSolid size="md" /></a
				>
			{/if}

			<button onclick={() => {}} use:copy={{ text: assistantLink, onCopy: showCopiedLink }}
				><LinkOutline
					class="inline-block h-6 w-6 text-blue-dark-30 hover:text-blue-dark-50 active:animate-ping"
				/></button
			>

			{#if editable && shareable && assistant.published}
				<button
					onclick={(event) => {
						event.preventDefault();
						sharedAssistantModalOpen = true;
					}}
					><GlobeOutline
						class="inline-block h-6 w-6 text-blue-dark-30 hover:text-blue-dark-50 active:animate-ping"
					/></button
				>
			{/if}
		</div>
	</Heading>
	<div class="mb-4 text-xs">Created by <b>{creator.name}</b></div>
	<div class="mb-4 max-h-24 overflow-y-auto font-light">
		{assistant.description || '(No description provided)'}
	</div>
	<div>
		<!-- eslint-disable svelte/no-navigation-without-resolve -->
		<a
			href={assistantLink}
			class="hover:text-blue-dark-100 flex w-36 items-center gap-2 rounded-full bg-orange p-2 px-4 text-sm font-medium text-white transition-all hover:bg-blue-dark-40 hover:text-white"
			>Start a chat <CirclePlusSolid size="sm" class="inline" /></a
		>
		<!-- eslint-enable svelte/no-navigation-without-resolve -->
	</div>
</div>

<Modal
	size="md"
	bind:open={copyAssistantModalOpen}
	onclose={() => (copyAssistantModalOpen = false)}
>
	<slot name="header">
		<Heading tag="h3" class="font-serif text-2xl font-medium text-blue-dark-40"
			>Copy Assistant</Heading
		>
	</slot>
	<p class="mb-4 text-blue-dark-40">
		This will create a private copy of <b>{assistant.name}</b> in the group you select. You can rename
		it below.
	</p>
	<div class="mb-6">
		<Label for="copy-name" class="mb-1 block text-sm font-medium text-blue-dark-50"
			>New Assistant Name</Label
		>
		<Input
			id="copy-name"
			name="copy-name"
			bind:value={copyName}
			placeholder={defaultCopyName(assistant.name)}
		/>
	</div>
	<div class="mb-6">
		<div class="mt-2 mb-1 flex items-center justify-between text-sm text-blue-dark-50">
			<Label for={`copy-target-${assistant.id}`} class="block text-sm font-medium text-blue-dark-50"
				>Copy to...</Label
			>

			{#if copyPermissionLoading}
				<span class="text-gray-500 italic">Checking permissions...</span>
			{:else if copyPermissionAllowed === true}
				<span class="flex items-center gap-1 text-green-700">
					<CheckCircleOutline class="h-4 w-4" /> Can create assistant in this Group
				</span>
			{:else}
				<span class="flex items-center gap-1 text-red-700">
					<ExclamationCircleOutline class="h-4 w-4" />
					{copyPermissionError || "Can't create assistant in this Group"}
				</span>
			{/if}
		</div>
		<Select
			id={`copy-target-${assistant.id}`}
			name={`copy-target-${assistant.id}`}
			bind:value={copyTargetClassId}
			size="md"
			class="w-full"
			onchange={() => checkCopyPermission(copyTargetClassId)}
		>
			{#each classOptions as option (option.id)}
				<option value={`${option.id}`}>
					{option.term ? `${option.name} (${option.term})` : option.name}
				</option>
			{/each}
		</Select>
	</div>
	<div class="flex justify-end gap-3">
		<Button color="light" onclick={() => (copyAssistantModalOpen = false)}>Cancel</Button>
		<Button
			color="blue"
			disabled={copyPermissionLoading || copyPermissionAllowed !== true}
			onclick={copyAssistant}>Copy</Button
		>
	</div>
</Modal>

<Modal bind:open={deleteAssistantModalOpen} size="xs" autoclose>
	<ConfirmationModal
		warningTitle={`Delete ${assistant?.name || 'this assistant'}?`}
		warningDescription="All threads associated with this assistant will become read-only."
		warningMessage="This action cannot be undone."
		cancelButtonText="Cancel"
		confirmText="delete"
		confirmButtonText="Delete assistant"
		on:cancel={() => (deleteAssistantModalOpen = false)}
		on:confirm={deleteAssistant}
	/>
</Modal>

<Modal
	outsideclose
	size="md"
	bind:open={notesAssistantModalOpen}
	onclose={() => (notesAssistantModalOpen = false)}
>
	<slot name="header">
		<Heading tag="h3" class="font-serif text-2xl font-medium text-blue-dark-40"
			>Assistant Notes</Heading
		>
	</slot>

	<p
		class="mb-5 max-h-96 overflow-y-scroll text-sm break-words whitespace-pre-wrap text-gray-700 dark:text-gray-300"
	>
		{assistant?.notes || 'No notes recorded for this bot.'}
	</p>
</Modal>
