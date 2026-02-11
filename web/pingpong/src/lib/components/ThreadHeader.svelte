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
	export let isLtiHeaderLayout: boolean = false;

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
		paddingClass={isLtiHeaderLayout
			? 'p-2 pt-3 pr-4 flex flex-row shrink rounded-t-4xl'
			: undefined}
	>
		<div slot="left" class="min-w-0 {isLtiHeaderLayout ? 'pt-2' : ''}">
			<div class="eyebrow eyebrow-dark ml-4">Select group</div>
			<Button class="{mainTextClass} max-w-full overflow-hidden {isLtiHeaderLayout ? 'pt-0.5' : ''}"
				><span class="truncate">{current?.name || 'Anonymous Session'}</span>
				<ChevronDownOutline
					size="sm"
					class="ml-4 inline-block h-8 w-8 shrink-0 rounded-full bg-white text-orange"
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
