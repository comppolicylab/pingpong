<script lang="ts">
	import { Button, Dropdown, DropdownItem, Search, Span } from 'flowbite-svelte';
	import { ChevronDownOutline, ArrowRightOutline, CogSolid } from 'flowbite-svelte-icons';
	import * as api from '$lib/api';
	import PageHeader, { mainTextClass } from './PageHeader.svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';

	export let classes: api.Class[];
	export let isOnClassPage: boolean;
	export let current: api.Class | null = null;
	export let canManage: boolean = false;
	export let isSharedPage: boolean = false;
	export let isNewHeaderLayout: boolean = false;

	$: sortedClasses = classes.sort((a: api.Class, b: api.Class) => a.name.localeCompare(b.name));
	let searchTerm = '';
	$: filteredClasses = sortedClasses.filter(
		(class_) => class_.name.toLowerCase().indexOf(searchTerm?.toLowerCase()) !== -1
	);

	let classDropdownOpen = false;
	const goToClass = async (clsId: number) => {
		classDropdownOpen = false;
		await goto(resolve(`/group/${clsId}`));
	};
</script>

{#if isSharedPage}
	<PageHeader>
		<div slot="left" class="min-w-0">
			<div class="eyebrow eyebrow-dark mb-2 ml-4">Shared Access</div>
			<Span class="{mainTextClass} overflow-hidden">{current?.name || 'no class'}</Span>
		</div>
		<div slot="right" class="flex flex-col items-end gap-2">
			{#if current}
				<div class="eyebrow eyebrow-dark mr-4 ml-4">Requires Login</div>

				<a
					href={resolve(`/group/${current.id}/assistant`)}
					class="hover:text-blue-dark-100 rounded-full bg-white p-2 px-4 text-sm font-medium text-blue-dark-50 transition-all hover:bg-blue-dark-40 hover:text-white"
					>View Group Page <ArrowRightOutline size="md" class="ml-1 inline-block text-orange" /></a
				>
			{/if}
		</div>
	</PageHeader>
{:else}
	<PageHeader
		paddingClass={isNewHeaderLayout
			? 'p-2 pt-3 pr-4 flex flex-row shrink rounded-t-4xl'
			: undefined}
	>
		<div slot="left" class="min-w-0 {isNewHeaderLayout ? 'pt-2' : ''}">
			<div class="eyebrow eyebrow-dark ml-4">Select group</div>
			<Button class="{mainTextClass} max-w-full overflow-hidden {isNewHeaderLayout ? 'pt-0.5' : ''}"
				><span class="truncate">{current?.name || 'Anonymous Session'}</span>
				<ChevronDownOutline
					size="sm"
					class="ml-4 inline-block h-8 w-8 shrink-0 rounded-full bg-white text-orange"
				/></Button
			>
			<Dropdown
				classContainer="min-h-0 overflow-hidden md:max-w-1/2 lg:max-w-1/3"
				bind:open={classDropdownOpen}
				placement="bottom-start"
			>
				<div slot="header" class="p-3">
					<Search size="md" bind:value={searchTerm} />
				</div>
				<div class="max-h-[400px] overflow-y-auto overscroll-contain">
					{#each filteredClasses as cls (cls.id)}
						<DropdownItem
							class="flex w-full items-center gap-4 py-3 text-base leading-6 hover:bg-blue-light-50"
							onclick={() => goToClass(cls.id)}>{cls.name}</DropdownItem
						>
					{/each}
					{#if filteredClasses.length === 0}
						<div
							class="px-4 py-4 text-sm font-medium font-semibold tracking-wide text-gray-500 uppercase select-none"
						>
							No groups found
						</div>
					{/if}
				</div>
			</Dropdown>
		</div>
		<div slot="right">
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
	</PageHeader>
{/if}
