<script lang="ts">
	import { resolve } from '$app/paths';
	import {
		Button,
		Heading,
		Helper,
		Input,
		Label,
		Table,
		TableBody,
		TableBodyCell,
		TableBodyRow,
		TableHead,
		TableHeadCell
	} from 'flowbite-svelte';
	import { ArrowRightOutline, PlusOutline, TrashBinOutline } from 'flowbite-svelte-icons';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import * as api from '$lib/api';
	import { headerState } from '$lib/stores/header';
	import { happyToast, sadToast } from '$lib/toast';

	export let data;

	let users: api.LectureLessonAccessUser[] = data.users;
	let newUserEmail = '';
	let addingUser = false;
	let removingUsers: Record<number, boolean> = {};

	$: isNewHeaderLayout = data.forceCollapsedLayout && data.forceShowSidebarButton;

	$: if (isNewHeaderLayout) {
		headerState.set({
			kind: 'nongroup',
			props: {
				title: 'Lecture Lesson Access',
				redirectUrl: '/admin',
				redirectName: 'Admin page'
			}
		});
	}

	const refresh = async () => {
		const response = await api.getLectureLessonAccessUsers(fetch).then(api.expandResponse);
		if (response.error || !response.data) {
			sadToast(response.error?.detail || 'Unable to refresh lecture lesson access');
			return;
		}
		users = response.data.users;
	};

	const addUser = async () => {
		const email = newUserEmail.trim();
		if (!email || addingUser) return;

		addingUser = true;
		try {
			const response = api.expandResponse(await api.addLectureLessonAccess(fetch, { email }));
			if (response.error) {
				sadToast(response.error.detail || 'Could not add lecture lesson access');
				return;
			}
			happyToast(response.data.added_access ? 'Access added' : 'User already has access');
			newUserEmail = '';
			await refresh();
		} catch (err) {
			console.error(err);
			sadToast('Could not add lecture lesson access');
		} finally {
			addingUser = false;
		}
	};

	const removeUser = async (userId: number) => {
		removingUsers = { ...removingUsers, [userId]: true };
		try {
			const response = api.expandResponse(await api.removeLectureLessonAccess(fetch, userId));
			if (response.error) {
				sadToast(response.error.detail || 'Could not remove lecture lesson access');
				return;
			}
			happyToast('Access removed');
			await refresh();
		} catch (err) {
			console.error(err);
			sadToast('Could not remove lecture lesson access');
		} finally {
			removingUsers = { ...removingUsers, [userId]: false };
		}
	};
</script>

<div class="relative flex h-full w-full flex-col">
	{#if !isNewHeaderLayout}
		<PageHeader>
			<div slot="left">
				<h2 class="text-color-blue-dark-50 px-4 py-3 font-serif text-3xl font-bold">
					Lecture Lesson Access
				</h2>
			</div>
			<div slot="right">
				<a
					href={resolve('/admin')}
					class="flex items-center gap-2 rounded-full bg-white p-2 px-4 text-sm font-medium text-blue-dark-50 transition-all hover:bg-blue-dark-40 hover:text-white"
					>Admin page <ArrowRightOutline size="md" class="text-orange" /></a
				>
			</div>
		</PageHeader>
	{/if}

	<div class="w-full space-y-8 p-12">
		<div class="space-y-2">
			<Heading tag="h2" class="text-dark-blue-40 max-w-max font-serif text-3xl font-medium"
				>Lecture Video and Lecture Slides Access</Heading
			>
			<p class="max-w-3xl text-sm text-gray-600">
				Users listed here can create Lecture Video and Lecture Slides assistants in groups where
				they already have permission to create assistants.
			</p>
		</div>

		<div class="flex max-w-3xl flex-col gap-3 rounded-xl border border-blue-100 bg-blue-50 p-4">
			<Label for="lecture-lesson-user-email" class="text-xs tracking-wide text-blue-900 uppercase">
				Add user by email
			</Label>
			<Helper>
				If the email does not belong to an existing account, an unverified user will be created.
			</Helper>
			<div class="flex flex-row gap-3">
				<Input
					type="email"
					id="lecture-lesson-user-email"
					name="lecture-lesson-user-email"
					placeholder="user@example.edu"
					class="sm:flex-1"
					bind:value={newUserEmail}
					disabled={addingUser}
				/>
				<Button
					onclick={addUser}
					disabled={addingUser || !newUserEmail.trim()}
					class="rounded-full bg-blue-dark-40 px-3 text-white hover:bg-blue-dark-50"
				>
					<PlusOutline class="mr-2" />
					Add access
				</Button>
			</div>
		</div>

		<Table class="w-full">
			<TableHead class="rounded-2xl bg-blue-light-40 p-1 tracking-wide text-blue-dark-50">
				<TableHeadCell>Name</TableHeadCell>
				<TableHeadCell>Email</TableHeadCell>
				<TableHeadCell></TableHeadCell>
			</TableHead>
			<TableBody>
				{#if users.length === 0}
					<TableBodyRow>
						<TableBodyCell colspan={3} class="py-3 text-sm text-gray-500">
							No users have explicit lecture lesson access.
						</TableBodyCell>
					</TableBodyRow>
				{/if}
				{#each users as user (user.id)}
					<TableBodyRow>
						<TableBodyCell class="py-2 font-medium whitespace-normal">
							{user.name || 'Unknown'}
						</TableBodyCell>
						<TableBodyCell class="py-2 font-normal whitespace-normal">
							{user.email || 'N/A'}
						</TableBodyCell>
						<TableBodyCell class="py-2">
							<Button
								pill
								size="sm"
								class="flex w-fit shrink-0 flex-row items-center justify-center gap-1.5 rounded-full border border-red-200 bg-white p-1 px-3 text-xs text-red-700 transition-all hover:bg-red-600 hover:text-white"
								disabled={!!removingUsers[user.id]}
								onclick={() => removeUser(user.id)}
							>
								<TrashBinOutline size="sm" class="mr-1" />
								Remove
							</Button>
						</TableBodyCell>
					</TableBodyRow>
				{/each}
			</TableBody>
		</Table>
	</div>
</div>
