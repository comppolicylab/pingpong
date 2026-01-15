<script lang="ts">
	import { Button, Dropdown, DropdownItem, Search, Span } from 'flowbite-svelte';
	import { ChevronDownOutline, ArrowRightOutline, CogSolid } from 'flowbite-svelte-icons';
	import * as api from '$lib/api';
	import PageHeader, { mainTextClass } from './PageHeader.svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';

	interface Props {
		classes: api.Class[];
		isOnClassPage: boolean;
		current?: api.Class | null;
		canManage?: boolean;
		isSharedPage?: boolean;
	}

	let {
		classes,
		isOnClassPage,
		current = null,
		canManage = false,
		isSharedPage = false
	}: Props = $props();

	let sortedClasses = $derived(
		classes.sort((a: api.Class, b: api.Class) => a.name.localeCompare(b.name))
	);
	let searchTerm = $state('');
	let filteredClasses = $derived(
		sortedClasses.filter(
			(class_) => class_.name.toLowerCase().indexOf(searchTerm?.toLowerCase()) !== -1
		)
	);

	let classDropdownOpen = $state(false);
	const goToClass = async (clsId: number) => {
		classDropdownOpen = false;
		await goto(resolve(`/group/${clsId}`));
	};
</script>

{#if isSharedPage}
	<PageHeader>
		{#snippet left()}
			<div>
				<div class="eyebrow eyebrow-dark mb-2 ml-4">Shared Access</div>
				<Span class={mainTextClass}>{current?.name || 'no class'}</Span>
			</div>
		{/snippet}
		{#snippet right()}
			<div class="flex flex-col items-end gap-2">
				{#if current}
					<div class="eyebrow eyebrow-dark mr-4 ml-4">Requires Login</div>

					<a
						href={resolve(`/group/${current.id}/assistant`)}
						class="hover:text-blue-dark-100 rounded-full bg-white p-2 px-4 text-sm font-medium text-blue-dark-50 transition-all hover:bg-blue-dark-40 hover:text-white"
						>View Group Page <ArrowRightOutline
							size="md"
							class="ml-1 inline-block text-orange"
						/></a
					>
				{/if}
			</div>
		{/snippet}
	</PageHeader>
{:else}
	<PageHeader>
		{#snippet left()}
			<div>
				<div class="eyebrow eyebrow-dark ml-4">Select group</div>
				<Button class={mainTextClass}
					>{current?.name || 'Anonymous Session'}
					<ChevronDownOutline
						size="sm"
						class="ml-4 inline-block h-8 w-8 rounded-full bg-white text-orange"
					/></Button
				>
				<Dropdown
					class="max-h-[400px] min-h-0 w-64 overflow-y-auto py-1"
					bind:open={classDropdownOpen}
				>
					<div slot="header" class="w-64 p-3">
						<Search size="md" bind:value={searchTerm} />
					</div>
					{#each filteredClasses as cls (cls.id)}
						<DropdownItem
							class="flex items-center gap-4 py-4 text-base text-sm font-medium font-semibold tracking-wide uppercase hover:bg-blue-light-50"
							onclick={() => goToClass(cls.id)}>{cls.name}</DropdownItem
						>
					{/each}
				</Dropdown>
			</div>
		{/snippet}
		{#snippet right()}
			<div>
				{#if current}
					{#if !isOnClassPage}
						<a
							href={resolve(`/group/${current.id}/assistant`)}
							class="hover:text-blue-dark-100 rounded-full bg-white p-2 px-4 text-sm font-medium text-blue-dark-50 transition-all hover:bg-blue-dark-40 hover:text-white"
							>View Group Page <ArrowRightOutline
								size="md"
								class="ml-1 inline-block text-orange"
							/></a
						>
					{:else if canManage}
						<a
							href={resolve(`/group/${current.id}/manage`)}
							class="hover:text-blue-dark-100 rounded-full bg-white p-2 px-4 text-sm font-medium text-blue-dark-50 transition-all hover:bg-blue-dark-40 hover:text-white"
							>Manage Group <CogSolid
								size="sm"
								class="relative -top-[1px] ml-1 inline-block text-orange"
							/></a
						>
					{/if}
				{/if}
			</div>
		{/snippet}
	</PageHeader>
{/if}
