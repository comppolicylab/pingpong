<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import * as api from '$lib/api';
	import {
		Select,
		Helper,
		Button,
		Label,
		Textarea,
		Hr,
		Checkbox,
		Table,
		TableHead,
		TableHeadCell,
		TableBody,
		TableBodyRow,
		TableBodyCell,
		Input,
		Tooltip
	} from 'flowbite-svelte';
	import { writable } from 'svelte/store';
	import { sadToast } from '$lib/toast';
	import {
		AngleDownOutline,
		LockSolid,
		QuestionCircleOutline,
		ExclamationCircleOutline,
		CheckCircleOutline,
		TrashBinOutline,
		PlusOutline,
		CheckOutline
	} from 'flowbite-svelte-icons';
	import PermissionsTable from './PermissionsTable.svelte';

	export let role: api.Role;
	export let classId: number;
	export let className: string = 'your group';
	export let isPrivate: boolean = false;
	export let permissions: { name: string; member: boolean; moderator: boolean }[] = [];
	let emailString: string = '';
	let verifiedEmails: api.EmailValidationResult[] = [];
	let unverifiedEmails: api.EmailValidationResult[] = [];
	$: newUsers = verifiedEmails.some((e) => !e.valid);
	let selectedRole: api.Role | undefined = role;
	let silentAdd = false;
	let showEmailForm = true;
	let showNameForm = false;
	let showResults = false;
	let permissionsModalOpen = false;
	let results: api.CreateUserResult[] = [];
	$: withErrors = results.some((r) => r.error);

	const dispatch = createEventDispatcher();

	const loading = writable(false);
	const submitEmailForm = async (evt: SubmitEvent) => {
		evt.preventDefault();
		$loading = true;

		const form = evt.target as HTMLFormElement;
		const formData = new FormData(form);
		const d = Object.fromEntries(formData.entries());

		const emails = (d.emails as string) || '';
		if (!emails) {
			$loading = false;
			sadToast('Emails are required');
			return;
		}
		emailString = emails;

		selectedRole = d.role as api.Role | undefined;
		if (!selectedRole) {
			$loading = false;
			sadToast('Role is required');
			return;
		}

		let rawValidateEmails = await api.validateEmails(fetch, classId, { emails: emailString });
		const validateEmailsResponse = api.expandResponse(rawValidateEmails);
		if (validateEmailsResponse.error) {
			$loading = false;
			return sadToast(validateEmailsResponse.error.detail || 'Unknown error validating emails.');
		}
		const emailList = validateEmailsResponse.data.results;
		verifiedEmails = emailList.filter((e) => e.valid);
		unverifiedEmails = emailList.filter((e) => !e.valid);

		silentAdd = d.notify !== 'on';

		$loading = false;
		showEmailForm = false;
		showNameForm = true;
	};

	const reverifyEmails = async (evt: Event) => {
		evt.preventDefault();
		$loading = true;

		let _emailList = verifiedEmails.concat(unverifiedEmails);
		let rawValidateEmails = await api.revalidateEmails(fetch, classId, { results: _emailList });

		const validateEmailsResponse = api.expandResponse(rawValidateEmails);
		if (validateEmailsResponse.error) {
			$loading = false;
			return sadToast(validateEmailsResponse.error.detail || 'Unknown error validating emails.');
		}
		const emailList = validateEmailsResponse.data.results;
		verifiedEmails = emailList.filter((e) => e.valid);
		unverifiedEmails = emailList.filter((e) => !e.valid);
		$loading = false;
	};

	const submitRequest = async (evt: Event) => {
		evt.preventDefault();
		$loading = true;

		const emailList = verifiedEmails.concat(unverifiedEmails);
		const request: api.CreateClassUsersRequest = {
			roles: emailList.map((e) => ({
				email: e.email,
				display_name: e.name,
				roles: {
					admin: selectedRole === 'admin',
					teacher: selectedRole === 'teacher',
					student: selectedRole === 'student'
				}
			})),
			silent: silentAdd
		};

		const result = await api.createClassUsers(fetch, classId, request);
		const response = api.expandResponse(result);
		if (response.error) {
			$loading = false;
			return sadToast(response.error.detail || 'Unknown error adding users.');
		}

		$loading = false;
		results = response.data.results;
		showNameForm = false;
		showResults = true;
	};

	const roles = api.ROLES.filter((role) => role !== 'admin').map((role) => ({
		value: role,
		name: api.ROLE_LABELS[role]
	}));
</script>

{#if showEmailForm}
	<form onsubmit={submitEmailForm}>
		<Label defaultClass="text-base font-normal rtl:text-right font-medium block" for="emails"
			>Emails</Label
		>
		<Helper helperClass="text-sm font-normal text-gray-500 dark:text-gray-300"
			>Enter email addresses separated by commas or newlines.</Helper
		>
		<Textarea class="mt-2 mb-4" id="emails" name="emails" rows={4} value={emailString} />

		<div class="flex items-center justify-between">
			<Label defaultClass="text-base font-normal rtl:text-right font-medium block" for="role"
				>Role</Label
			>
			<Button
				class="flex flex-row items-center gap-1 p-0 text-sm font-normal text-gray-500 hover:underline"
				onclick={() => (permissionsModalOpen = !permissionsModalOpen)}
				ontouchstart={() => (permissionsModalOpen = !permissionsModalOpen)}
			>
				{permissionsModalOpen ? 'Hide' : 'Show'} permissions
				{#if permissionsModalOpen}
					<AngleDownOutline class="h-4 w-4" />
				{:else}
					<QuestionCircleOutline class="h-4 w-4" />
				{/if}
			</Button>
		</div>
		<div
			class="overflow-hidden transition-all duration-300 ease-in-out"
			class:max-h-0={!permissionsModalOpen}
			class:max-h-[500px]={permissionsModalOpen}
			class:opacity-0={!permissionsModalOpen}
			class:opacity-100={permissionsModalOpen}
		>
			<div class="relative my-4 overflow-hidden rounded-lg shadow-md">
				{#if isPrivate}
					<div
						class="border-gradient-to-r flex items-center bg-gradient-to-r from-gray-800 to-gray-600 p-4 text-sm text-white"
					>
						<LockSolid class="mr-3 h-8 w-8" />
						<span>
							Threads and assistants are private in your group, so Moderators have limited
							permissions compared to a non-private group.
						</span>
					</div>
				{/if}
				<div
					class="overflow-hidden rounded-lg border border-gray-300 bg-white"
					class:rounded-lg={!isPrivate}
					class:rounded-b-lg={isPrivate}
				>
					<PermissionsTable {permissions} />
				</div>
			</div>
		</div>
		<Helper helperClass="text-sm font-normal text-gray-500 dark:text-gray-300">
			<div>Choose a user role to grant permissions to these users to view the group.</div>
		</Helper>
		<Select
			id="role"
			name="role"
			class="mt-2 mb-4 py-1.5"
			placeholder="Select a user role..."
			value={selectedRole}
			items={roles}
		/>
		<Helper helperClass="text-base font-normal rtl:text-right font-medium block"
			>Notify people</Helper
		>
		<Checkbox checked id="notify" name="notify" class="mt-1 text-sm font-normal"
			>Let users know they have access to {className} on PingPong</Checkbox
		>
		<Hr />

		<div class="flex flex-row justify-end gap-2">
			<Button
				type="button"
				pill
				class="rounded-full border border-blue-dark-40 bg-blue-light-50 text-blue-dark-50 hover:bg-blue-light-40"
				disabled={$loading}
				onclick={() => dispatch('cancel')}
				ontouchstart={() => dispatch('cancel')}>Cancel</Button
			>
			<Button
				type="submit"
				pill
				class="border border-orange-dark bg-orange text-white hover:bg-orange-dark"
				disabled={$loading}>Next</Button
			>
		</div>
	</form>
{:else if showNameForm}
	{#if unverifiedEmails.length > 0}
		<div
			class="flex items-center rounded-lg border-2 border-red-800 px-4 py-3 text-sm text-gray-800"
		>
			<ExclamationCircleOutline class="mr-3 h-8 w-8 text-red-800" />
			<div class="flex flex-col">
				<span
					class="inline-block bg-gradient-to-r from-red-800 to-red-400 bg-clip-text font-bold text-transparent"
					>Users with invalid emails</span
				><span
					>We were unable to confirm the emails you entered for the following users. Please correct
					these addresses or delete these users before continuing.</span
				>
			</div>
		</div>

		<Table class="mt-2 min-w-full text-left text-sm text-gray-500">
			<TableHead theadClass="text-base" class="bg-gray-200">
				<TableHeadCell padding="px-3 py-1" class="font-medium text-gray-900"
					>Name <span class="font-light">(optional)</span></TableHeadCell
				>
				<TableHeadCell padding="px-3 py-1" class="font-medium text-gray-900">Email</TableHeadCell>
				<TableHeadCell padding="px-3 py-1" class="font-medium text-gray-900"></TableHeadCell>
				<TableHeadCell padding="px-3 py-1" class="font-medium text-gray-900"></TableHeadCell>
			</TableHead>
			<TableBody>
				{#each unverifiedEmails as tuple, index (tuple.email)}
					<TableBodyRow class="px-2 py-1">
						<!-- Name Input -->
						<TableBodyCell class="px-3 py-1">
							<Input
								type="text"
								placeholder="Name"
								class="w-full rounded-sm border px-2 py-1 font-light"
								bind:value={tuple.name}
							/>
						</TableBodyCell>

						<!-- Email Input -->
						<TableBodyCell class="px-3 py-1">
							<Input
								type="email"
								placeholder="Email"
								class="w-full rounded-sm border px-2 py-1 font-light"
								bind:value={tuple.email}
							/>
						</TableBodyCell>

						<!-- Email Error Reporting -->
						{#if tuple.error}
							<TableBodyCell class="px-1 py-1">
								<QuestionCircleOutline class="h-6 w-6 text-gray-400" />
								<Tooltip arrow={false} class="overflow-visible text-xs font-light text-wrap"
									>{tuple.error}</Tooltip
								>
							</TableBodyCell>
						{/if}

						<TableBodyCell class="px-3 py-1">
							<Button
								type="button"
								onclick={() => {
									unverifiedEmails = unverifiedEmails.filter((_, i) => i !== index);
								}}
								class="p-0"
							>
								<TrashBinOutline class="h-6 w-6 text-red-500" />
							</Button>
						</TableBodyCell>
					</TableBodyRow>
				{/each}
			</TableBody>
		</Table>
		<Hr />
	{/if}
	<div
		class="flex items-center rounded-lg border-2 border-green-600 px-4 py-2 text-sm text-gray-800"
	>
		<CheckCircleOutline class="mr-3 h-8 w-8 text-green-600" />
		The following users are ready to be added to the group.
	</div>
	<Table class="mt-2 min-w-full text-left text-sm text-gray-500">
		<TableHead theadClass="text-base" class="bg-gray-200">
			<TableHeadCell padding="px-3 py-1" class="font-medium text-gray-900"
				>Name <span class="font-light">(optional)</span></TableHeadCell
			>
			<TableHeadCell padding="px-3 py-1" class="font-medium text-gray-900">Email</TableHeadCell>
			<TableHeadCell padding="px-3 py-1" class="font-medium text-gray-900"></TableHeadCell>
		</TableHead>
		<TableBody>
			{#each verifiedEmails as tuple, index (tuple.email)}
				<TableBodyRow class="px-2 py-1">
					<!-- Name Input -->
					<TableBodyCell class="px-3 py-1">
						{#if tuple.isUser}
							<span>{tuple.name || ''}</span>
							<Tooltip arrow={false} class="overflow-visible text-xs font-light text-wrap"
								>This user already has a profile, so you cannot edit their name.</Tooltip
							>
						{:else}
							<Input
								type="text"
								placeholder="Name"
								class="w-full rounded-sm border px-2 py-1 font-light"
								bind:value={tuple.name}
								disabled={tuple.isUser}
							/>
						{/if}
					</TableBodyCell>

					<!-- Email Input -->
					<TableBodyCell class="px-3 py-1">
						{#if tuple.valid}
							<span>{tuple.email}</span>
							<Tooltip
								placement="bottom"
								arrow={false}
								class="overflow-visible text-xs font-light text-wrap"
								>This email has been verified, so you cannot edit it.</Tooltip
							>
						{:else}
							<Input
								type="email"
								placeholder="Email"
								class="w-full rounded-sm border px-2 py-1 font-light"
								bind:value={tuple.email}
								disabled={tuple.valid}
							/>
						{/if}
					</TableBodyCell>

					<TableBodyCell class="px-3 py-1">
						<Button
							type="button"
							onclick={() => {
								verifiedEmails = verifiedEmails.filter((_, i) => i !== index);
							}}
							class="p-0"
						>
							<TrashBinOutline class="h-6 w-6 text-red-500" />
						</Button>
					</TableBodyCell>
				</TableBodyRow>
			{/each}
		</TableBody>
	</Table>
	<Button
		class="text-blue-500 hover:underline"
		onclick={() => {
			verifiedEmails = [
				...verifiedEmails,
				{ email: '', name: '', valid: false, isUser: false, error: '' }
			];
		}}><div class="flex flex-row gap-1"><PlusOutline /><span>Add another user</span></div></Button
	>
	<Hr />

	<div class="flex flex-row justify-end gap-2">
		<Button
			type="button"
			pill
			class="bg-blue-ligaddUsersht-50 rounded-full border border-blue-dark-40 text-blue-dark-50 hover:bg-blue-light-40"
			disabled={$loading}
			onclick={() => dispatch('cancel')}
			ontouchstart={() => dispatch('cancel')}>Cancel</Button
		>
		{#if unverifiedEmails.length > 0 || newUsers}
			<Button
				type="submit"
				pill
				class="border border-orange-dark bg-orange text-white hover:bg-orange-dark"
				disabled={$loading}
				onclick={reverifyEmails}>Next</Button
			>
		{:else if verifiedEmails.length > 0}
			<Button
				type="submit"
				pill
				class="border border-orange-dark bg-orange text-white hover:bg-orange-dark"
				disabled={$loading}
				onclick={submitRequest}>Add Users</Button
			>
		{/if}
	</div>
{:else if showResults}
	<div class="flex flex-col items-center">
		<CheckCircleOutline class="h-12 w-12 text-green-600" />
		<div class="mt-2 text-xl font-bold text-gray-800">Success!</div>
		{#if withErrors}
			<div class="mt-1 mb-3 px-10 text-gray-500">
				Your request was successfully processed. We were unable to add some users. We've included
				the errors we faced below.
			</div>
		{:else}
			<div class="mt-1 mb-3 px-10 text-gray-500">
				All users have been successfully added to your PingPing group.
			</div>
		{/if}
		<Table class="mt-2 mb-4 text-left text-sm text-gray-500">
			<TableHead theadClass="text-base" class="bg-gray-200">
				<TableHeadCell padding="px-3 py-1" class="font-medium text-gray-900">Name</TableHeadCell>
				<TableHeadCell padding="px-3 py-1" class="font-medium text-gray-900">Email</TableHeadCell>
				<TableHeadCell padding="px-3 py-1" class="font-medium text-gray-900"></TableHeadCell>
			</TableHead>
			<TableBody>
				{#each results as tuple (tuple.email)}
					<TableBodyRow class="px-2 py-1">
						<!-- Name Input -->
						<TableBodyCell class="px-3 py-1">
							<span>{tuple.display_name || ''}</span>
						</TableBodyCell>

						<!-- Email Input -->
						<TableBodyCell class="px-3 py-1">
							<span>{tuple.email}</span>
						</TableBodyCell>

						<TableBodyCell class="px-3 py-1">
							{#if tuple.error}
								<span class="text-light text-wrap text-red-700">{tuple.error}</span>
							{:else}
								<CheckOutline class="h-6 w-6 text-green-600" />
							{/if}
						</TableBodyCell>
					</TableBodyRow>
				{/each}
			</TableBody>
		</Table>
		<Button
			pill
			class="bg-blue-ligaddUsersht-50 rounded-full border border-blue-dark-40 text-blue-dark-50 hover:bg-blue-light-40"
			onclick={() => dispatch('close')}
			ontouchstart={() => dispatch('close')}>Done</Button
		>
	</div>
{/if}
