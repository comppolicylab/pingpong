<script lang="ts">
	import {
		Accordion,
		AccordionItem,
		Button,
		Checkbox,
		Input,
		Label,
		Radio,
		Select
	} from 'flowbite-svelte';
	import { createEventDispatcher } from 'svelte';
	import { FileCopyOutline } from 'flowbite-svelte-icons';
	import AzureLogo from './AzureLogo.svelte';
	import OpenAiLogo from './OpenAILogo.svelte';
	import type { CopyClassRequestInfo, Institution } from '$lib/api';

	export let groupName: string;
	let displayGroupName = groupName + ' (Copy)';
	export let groupSession: string;
	export let institutions: Institution[] = [];
	export let currentInstitutionId: number | null = null;
	export let makePrivate = false;
	export let anyCanPublishThread = false;
	export let anyCanShareAssistant = false;
	export let assistantPermissions: string = 'create:0,publish:0,upload:0';
	export let aiProvider = '';

	let disableAnyCanShareAssistants = assistantPermissions.includes('publish:0');
	$: {
		disableAnyCanShareAssistants = assistantPermissions.includes('publish:0');
		if (disableAnyCanShareAssistants) {
			anyCanShareAssistant = false;
		}
	}

	let assistantCopy: 'moderators' | 'all' = 'moderators';
	let userCopy: 'moderators' | 'all' = 'moderators';
	let selectedInstitutionId = currentInstitutionId !== null ? currentInstitutionId.toString() : '';
	$: institutionOptions = institutions.map((inst) => ({
		value: inst.id.toString(),
		name: inst.name
	}));
	$: {
		const hasValidSelection = institutions.some(
			(inst) => inst.id.toString() === selectedInstitutionId
		);
		if ((!selectedInstitutionId || !hasValidSelection) && institutions.length > 0) {
			const preferred =
				institutions.find((inst) => inst.id === currentInstitutionId) || institutions[0];
			if (preferred) {
				selectedInstitutionId = preferred.id.toString();
			}
		}
	}

	let copyClassInfo: CopyClassRequestInfo;
	$: copyClassInfo = {
		groupName: displayGroupName,
		groupSession,
		institutionId: selectedInstitutionId
			? parseInt(selectedInstitutionId, 10)
			: (currentInstitutionId ?? null),
		makePrivate,
		anyCanPublishThread,
		anyCanShareAssistant,
		assistantPermissions,
		assistantCopy,
		userCopy
	};

	const dispatch = createEventDispatcher();

	const asstPermOptions = [
		{ value: 'create:0,publish:0,upload:0', name: 'Do not allow members to create' },
		{ value: 'create:1,publish:0,upload:1', name: 'Members can create but not publish' },
		{ value: 'create:1,publish:1,upload:1', name: 'Members can create and publish' }
	];
</script>

<div class="px-2 text-center">
	<FileCopyOutline class="mx-auto mb-4 h-12 w-12 text-blue-dark-40" />
	<h3 class="mb-1 text-xl font-bold text-gray-900 dark:text-white">Clone Group</h3>
	<p class="mx-auto mb-5 w-2/3 text-gray-700 dark:text-gray-300">
		Configure the new group and choose what content to copy over from the original group.
	</p>
	<div class="mb-4 px-4">
		<Accordion class="w-full text-left" flush multiple>
			<AccordionItem paddingFlush="py-2" open>
				<span slot="header" class="mr-3 w-full"
					><div class="flex w-full flex-row items-center justify-between space-x-2">
						<div>Group Details</div>
					</div></span
				>
				<div class="my-3 grid gap-x-6 gap-y-6 md:grid-cols-2">
					<div>
						<Label for="name" class="mb-1">Name</Label>
						<Input id="name" name="name" bind:value={displayGroupName} />
					</div>
					<div>
						<Label for="term" class="mb-1">Session</Label>
						<Input id="term" name="term" bind:value={groupSession} />
					</div>
					<div class="md:col-span-2">
						<Label for="institution" class="mb-1">Institution</Label>
						{#if institutions.length > 0}
							<Select
								id="institution"
								name="institution"
								bind:value={selectedInstitutionId}
								class="truncate"
								items={institutionOptions}
							/>
						{:else}
							<p class="text-sm text-gray-500">
								No eligible institutions available for this account.
							</p>
						{/if}
					</div>
					<Checkbox id="make_private" name="make_private" bind:checked={makePrivate}>
						Make threads and assistants private
					</Checkbox>

					<Checkbox
						id="any_can_publish_thread"
						name="any_can_publish_thread"
						bind:checked={anyCanPublishThread}>Allow members to publish threads</Checkbox
					>
					<div class="content-center text-sm font-medium text-gray-900">
						Assistant Permissions for Members
					</div>
					<Select
						items={asstPermOptions}
						bind:value={assistantPermissions}
						name="asst_perm"
						class="truncate"
					/>
					<Checkbox
						id="any_can_share_assistant"
						name="any_can_share_assistant"
						disabled={disableAnyCanShareAssistants}
						class={'col-span-2 ' +
							(disableAnyCanShareAssistants ? 'text-gray-400' : '!text-gray-900 !opacity-100')}
						bind:checked={anyCanShareAssistant}
						>Allow members to create public links for assistants</Checkbox
					>
				</div>
			</AccordionItem>
			<AccordionItem paddingFlush="py-2">
				<span slot="header" class="mr-3 w-full"
					><div class="flex w-full flex-row items-center justify-between space-x-2">
						<div>AI Provider</div>
						<div class="flex flex-row items-center gap-1 text-sm font-light">
							{#if aiProvider === 'azure'}
								<AzureLogo size="4" />
								<div>Azure</div>
							{:else if aiProvider === 'openai'}
								<OpenAiLogo size="4" />
								<div>OpenAI</div>
							{:else}
								<div>Same as original group</div>
							{/if}
						</div>
					</div></span
				>
				<p class="mb-2 text-sm font-light text-gray-500">
					Your new group will share the same files with the original group, which requires the same
					billing details, including your AI Provider.
				</p>
			</AccordionItem>
			<AccordionItem paddingFlush="py-2">
				<span slot="header" class="mr-3 w-full"
					><div class="flex w-full flex-row items-center justify-between space-x-2">
						<div>Assistants</div>
						<div class="text-sm font-light">
							{#if assistantCopy === 'moderators'}
								Copy only published Moderator Assistants
							{:else if assistantCopy === 'all'}
								Copy all published Assistants
							{:else}
								No assistants will be copied
							{/if}
						</div>
					</div></span
				>
				<p class="mb-2 text-sm font-light text-gray-500">
					Choose which assistants to copy over to the new group. You can also create new assistants
					in the new group. If you choose to copy assistants created by members, they will be added
					as users in the new group.
				</p>
				<Radio name="moderatorOnlyAssistants" value="moderators" bind:group={assistantCopy}
					>Copy only&nbsp;<span class="italic">published</span>&nbsp;Moderator Assistants</Radio
				>
				<Radio
					name="allAssistants"
					value="all"
					bind:group={assistantCopy}
					onclick={() => {
						userCopy = 'all';
					}}
					>Copy all&nbsp;<span class="italic">published</span>&nbsp;Assistants, including those
					created by members</Radio
				>
			</AccordionItem>
			<AccordionItem paddingFlush="py-2">
				<span slot="header" class="mr-3 w-full"
					><div class="flex w-full flex-row items-center justify-between space-x-2">
						<div>Users</div>
						<div class="text-sm font-light">
							{#if userCopy === 'moderators'}
								Copy only Moderators
							{:else if userCopy === 'all'}
								Copy all users
							{:else}
								No users will be copied
							{/if}
						</div>
					</div></span
				>
				<p class="mb-2 text-sm font-light text-gray-500">
					Choose which users to copy over to the new group. You can also add new users in the new
					group. If you choose to copy assistants created by members, all members will be added as
					users in the new group.
				</p>
				<Radio
					name="moderatorOnlyUsers"
					value="moderators"
					bind:group={userCopy}
					disabled={assistantCopy === 'all'}>Copy only Moderators</Radio
				>
				{#if assistantCopy === 'all'}
					<p class="mb-2 text-sm text-gray-500">
						If you copy all assistants, all users will be copied as well.
					</p>
				{/if}
				<Radio name="allUsers" value="all" bind:group={userCopy}>Copy all users</Radio>
			</AccordionItem>
		</Accordion>
	</div>
	<div class="flex justify-center gap-4">
		<Button pill color="alternative" onclick={() => dispatch('cancel')}>Cancel</Button>
		<Button pill outline color="blue" onclick={() => dispatch('confirm', copyClassInfo)}
			>Clone Group</Button
		>
	</div>
</div>
