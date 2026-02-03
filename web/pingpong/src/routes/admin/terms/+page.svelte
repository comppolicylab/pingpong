<script lang="ts">
	import { invalidateAll } from '$app/navigation';
	import { resolve } from '$app/paths';
	import * as api from '$lib/api';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import { happyToast, sadToast } from '$lib/toast';
	import dayjs from 'dayjs';
	import {
		Button,
		Heading,
		Hr,
		Table,
		TableBody,
		TableBodyCell,
		TableBodyRow,
		TableHead,
		TableHeadCell
	} from 'flowbite-svelte';
	import { ArrowRightOutline, PlusOutline } from 'flowbite-svelte-icons';
	import { ltiHeaderState } from '$lib/stores/ltiHeader';

	export let data;

	$: agreements = data.agreements;
	$: policies = data.policies;

	$: isLtiHeaderLayout = data.forceCollapsedLayout && data.forceShowSidebarButton;

	// Update props reactively when data changes
	$: if (isLtiHeaderLayout) {
		ltiHeaderState.set({
			kind: 'nongroup',
			props: {
				title: 'User Agreements',
				redirectUrl: '/admin',
				redirectName: 'Admin page'
			}
		});
	}

	const handleEnablePolicy = async (policy: api.AgreementPolicy) => {
		if (
			!confirm(
				`You are about to enable policy "${policy.name}". This will make it active for eligible users and you will not be able to edit it. Are you sure you want to continue?`
			)
		) {
			return;
		}
		const response = await api.toggleAgreementPolicy(fetch, policy.id, { action: 'enable' });
		const expanded = api.expandResponse(response);
		if (expanded.error) {
			return sadToast(`Failed to enable policy: ${expanded.error.detail}`);
		}
		happyToast(`Policy ${policy.name} enabled.`, 3000);
		await invalidateAll();
	};

	const handleDisablePolicy = async (policy: api.AgreementPolicy) => {
		if (
			!confirm(
				`You are about to archive policy "${policy.name}". This will make it inactive for eligible users. You will have to create a new policy to show it to users again. Are you sure you want to continue?`
			)
		) {
			return;
		}
		const response = await api.toggleAgreementPolicy(fetch, policy.id, { action: 'disable' });
		const expanded = api.expandResponse(response);
		if (expanded.error) {
			return sadToast(`Failed to archive policy: ${expanded.error.detail}`);
		}
		happyToast(`Policy ${policy.name} archived.`, 3000);
		await invalidateAll();
	};
</script>

<div class="relative flex h-full w-full flex-col">
	{#if !isLtiHeaderLayout}
		<PageHeader>
			<div slot="left">
				<h2 class="text-color-blue-dark-50 px-4 py-3 font-serif text-3xl font-bold">
					User Agreements
				</h2>
			</div>
			<div slot="right">
				<a
					href={resolve(`/admin`)}
					class="flex items-center gap-2 rounded-full bg-white p-2 px-4 text-sm font-medium text-blue-dark-50 transition-all hover:bg-blue-dark-40 hover:text-white"
					>Admin page <ArrowRightOutline size="md" class="text-orange" /></a
				>
			</div>
		</PageHeader>
	{/if}
	<div class="h-full w-full overflow-y-auto p-12">
		<div class="mb-4 flex flex-row flex-wrap items-center justify-between gap-y-4">
			<Heading
				tag="h2"
				class="text-dark-blue-40 mr-5 max-w-max shrink-0 font-serif text-3xl font-medium"
				>Manage User Agreements</Heading
			>
			<Button
				pill
				size="sm"
				class="flex flex-row gap-2 border border-solid border-blue-dark-40 bg-white text-blue-dark-40 hover:bg-blue-dark-40 hover:text-white"
				href="/admin/terms/agreement/new"><PlusOutline />New Agreement</Button
			>
		</div>
		<div class="flex flex-col gap-4">
			<Table class="w-full overflow-visible">
				<TableHead class="rounded-2xl bg-blue-light-40 p-1 tracking-wide text-blue-dark-50">
					<TableHeadCell>Agreement Name</TableHeadCell>
					<TableHeadCell>Last Updated</TableHeadCell>
					<TableHeadCell></TableHeadCell>
				</TableHead>
				<TableBody>
					{#each agreements as agreement (agreement.id)}
						<TableBodyRow>
							<TableBodyCell class="py-2 font-medium whitespace-normal"
								>{agreement.name}</TableBodyCell
							>
							<TableBodyCell class="py-2 font-normal whitespace-normal">
								{dayjs.utc(agreement.updated ?? agreement.created).fromNow()}
							</TableBodyCell>
							<TableBodyCell class="py-2">
								<Button
									pill
									size="sm"
									class="flex w-fit shrink-0 flex-row items-center justify-center gap-1.5 rounded-full border border-blue-dark-40 bg-white p-1 px-3 text-xs text-blue-dark-40 transition-all hover:bg-blue-dark-40 hover:text-white"
									href={`/admin/terms/agreement/${agreement.id}`}
								>
									Edit
								</Button>
							</TableBodyCell>
						</TableBodyRow>
					{/each}
				</TableBody>
			</Table>
		</div>
		<Hr class="my-8" />
		<div class="mb-4 flex flex-row flex-wrap items-center justify-between gap-y-4">
			<Heading
				tag="h2"
				class="text-dark-blue-40 mr-5 mb-4 max-w-max shrink-0 font-serif text-3xl font-medium"
				>Manage Agreement Policies</Heading
			>
			<Button
				pill
				size="sm"
				class="flex flex-row gap-2 border border-solid border-blue-dark-40 bg-white text-blue-dark-40 hover:bg-blue-dark-40 hover:text-white"
				href="/admin/terms/policy/new"><PlusOutline />New Policy</Button
			>
		</div>
		<div>
			<Table class="w-full">
				<TableHead class="rounded-2xl bg-blue-light-40 p-1 tracking-wide text-blue-dark-50">
					<TableHeadCell>Policy Name</TableHeadCell>
					<TableHeadCell>Agreement</TableHeadCell>
					<TableHeadCell>Status</TableHeadCell>
					<TableHeadCell>Enabled</TableHeadCell>
					<TableHeadCell>Archived</TableHeadCell>
					<TableHeadCell></TableHeadCell>
				</TableHead>
				<TableBody>
					{#each policies as policy (policy.id)}
						<TableBodyRow>
							<TableBodyCell class="py-2 font-medium whitespace-normal">{policy.name}</TableBodyCell
							>
							<TableBodyCell class="py-2 font-normal whitespace-normal">
								{policy.agreement.name}
							</TableBodyCell>
							<TableBodyCell
								class="py-2 text-sm font-normal font-semibold whitespace-normal uppercase {policy.not_before
									? policy.not_after
										? 'text-amber-700'
										: 'text-green-700'
									: 'text-sky-700'}"
							>
								{policy.not_before ? (policy.not_after ? 'Archived' : 'Active') : 'Draft'}
							</TableBodyCell>
							<TableBodyCell class="py-2 font-normal whitespace-normal">
								{policy.not_before ? dayjs.utc(policy.not_before).fromNow() : ''}
							</TableBodyCell>
							<TableBodyCell class="py-2 font-normal whitespace-normal">
								{policy.not_after ? dayjs.utc(policy.not_after).fromNow() : ''}
							</TableBodyCell>
							<TableBodyCell class="py-2">
								<div class="flex flex-row gap-2">
									<Button
										pill
										size="sm"
										class="flex w-fit shrink-0 flex-row items-center justify-center gap-1.5 rounded-full border border-blue-dark-40 bg-white p-1 px-3 text-xs text-blue-dark-40 transition-all hover:bg-blue-dark-40 hover:text-white"
										href={`/admin/terms/policy/${policy.id}`}
									>
										{policy.not_before ? 'View' : 'Edit'}
									</Button>
									{#if !policy.not_before}
										<Button
											pill
											size="sm"
											class="flex w-fit shrink-0 flex-row items-center justify-center gap-1.5 rounded-full border border-green-800 bg-white p-1 px-3 text-xs text-green-800 transition-all hover:bg-green-800 hover:text-white"
											onclick={() => handleEnablePolicy(policy)}
										>
											Enable Policy
										</Button>
									{:else if !policy.not_after}
										<Button
											pill
											size="sm"
											class="flex w-fit shrink-0 flex-row items-center justify-center gap-1.5 rounded-full border border-amber-800 bg-white p-1 px-3 text-xs text-amber-800 transition-all hover:bg-amber-800 hover:text-white"
											onclick={() => handleDisablePolicy(policy)}
										>
											Archive Policy
										</Button>
									{/if}
								</div>
							</TableBodyCell>
						</TableBodyRow>
					{/each}
				</TableBody>
			</Table>
		</div>
	</div>
</div>
