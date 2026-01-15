<script lang="ts">
	import dayjs from '$lib/time';
	import { page } from '$app/stores';
	import { Button, Select, Hr } from 'flowbite-svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import { updateSearch, getValue } from '$lib/urlstate';
	import { resolve } from '$app/paths';

	let { data } = $props();

	let institutionOptions: { value: string; name: string }[] = $derived([
		{ value: '0', name: 'All' },
		...data.institutions
			.sort((a, b) => a.name.localeCompare(b.name))
			.map((inst) => ({ value: `${inst.id}`, name: inst.name }))
	]);
	let instSearch = $derived(parseInt($page.url.searchParams.get('institution_id') || '0', 10));
	let classes = $derived(
		(data.classes || [])
			.filter((cls) => (instSearch ? cls.institution_id === instSearch : true))
			.sort((a, b) => a.name.localeCompare(b.name))
	);
</script>

<div class="flex h-full w-full flex-col">
	<PageHeader>
		{#snippet left()}
			<h2 class="text-color-blue-dark-50 px-4 pt-6 pb-3 font-serif text-3xl font-bold">Admin</h2>
		{/snippet}
	</PageHeader>

	<!-- TODO: search is not yet fully supported. -->

	<div class="grid min-h-0 shrink grow gap-12 p-12 sm:grid-cols-[2fr_1fr]">
		<div class="overflow-y-auto sm:col-start-2 sm:col-end-3">
			<div class="flex flex-col gap-4">
				<div>
					<label for="institution" class="block pt-8 pb-2 text-xs tracking-wide uppercase"
						>Filter by <b>Institution</b></label
					>
					<Select
						items={institutionOptions}
						onchange={(e) => updateSearch('institution_id', getValue(e.target))}
						value={`${instSearch}`}
						name="institution"
					/>
				</div>
				<div>
					<Button
						class="rounded-full bg-orange text-white hover:bg-orange-dark"
						href="/admin/createGroup">Create a new group</Button
					>
				</div>
				{#if data.statistics}
					<Hr />
					<div class="mb-6 flex flex-col gap-2">
						<span class="mb-3 text-center text-lg font-medium uppercase">PingPong Stats</span>
						<div
							class="flex flex-col gap-2 rounded-2xl bg-gold-light px-8 py-4 pt-6 pb-6 text-center"
						>
							<span class="text-5xl font-light text-blue-dark-40">
								{data.statistics.institutions}
							</span>
							<span class="text-md font-medium text-blue-dark-50 uppercase">Institutions</span>
						</div>
						<div
							class="flex flex-col gap-2 rounded-2xl bg-gold-light px-8 py-4 pt-6 pb-6 text-center"
						>
							<span class="text-5xl font-light text-blue-dark-40">
								{data.statistics.classes}
							</span>
							<span class="text-md font-medium text-blue-dark-50 uppercase">Groups</span>
						</div>
						<div
							class="flex flex-col gap-2 rounded-2xl bg-gold-light px-8 py-4 pt-6 pb-6 text-center"
						>
							<span class="text-5xl font-light text-blue-dark-40">
								{data.statistics.users}
							</span>
							<span class="text-md font-medium text-blue-dark-50 uppercase">Users</span>
						</div>
						{#if data.statistics.users}
							<div
								class="flex flex-col gap-2 rounded-2xl bg-gold-light px-8 py-4 pt-6 pb-6 text-center"
							>
								<span class="text-5xl font-light text-blue-dark-40">
									{(data.statistics.enrollments / data.statistics.users).toFixed(1)}
								</span>
								<span class="text-md font-medium text-blue-dark-50 uppercase"
									>Average enrollments<br />per user</span
								>
							</div>
						{/if}
						<div
							class="flex flex-col gap-2 rounded-2xl bg-gold-light px-8 py-4 pt-6 pb-6 text-center"
						>
							<span class="text-5xl font-light text-blue-dark-40">
								{data.statistics.assistants}
							</span>
							<span class="text-md font-medium text-blue-dark-50 uppercase">Assistants</span>
						</div>
						<div
							class="flex flex-col gap-2 rounded-2xl bg-gold-light px-8 py-4 pt-6 pb-6 text-center"
						>
							<span class="text-5xl font-light text-blue-dark-40">
								{data.statistics.threads}
							</span>
							<span class="text-md font-medium text-blue-dark-50 uppercase">Threads</span>
						</div>
						<div
							class="flex flex-col gap-2 rounded-2xl bg-gold-light px-8 py-4 pt-6 pb-6 text-center"
						>
							<span class="text-5xl font-light text-blue-dark-40">
								{data.statistics.files}
							</span>
							<span class="text-md font-medium text-blue-dark-50 uppercase">Files</span>
						</div>
					</div>
				{/if}
				<Hr />
				<Button
					class="rounded-full bg-orange text-white hover:bg-orange-dark"
					href="/admin/providers">Manage External Login Providers</Button
				>
				{#if data.admin?.isRootAdmin}
					<Button
						class="rounded-full bg-orange text-white hover:bg-orange-dark"
						href="/admin/institutions">Manage Institutions</Button
					>
					<Button class="rounded-full bg-orange text-white hover:bg-orange-dark" href="/admin/lti"
						>Manage LTI Registrations</Button
					>
				{/if}
				<Button class="rounded-full bg-orange text-white hover:bg-orange-dark" href="/admin/terms"
					>Manage User Agreements</Button
				>
			</div>
		</div>

		<div class="h-full overflow-y-auto sm:col-start-1 sm:col-end-2 sm:row-start-1">
			<h3 class="border-b border-gray-200 pb-1 text-2xl font-normal">Groups</h3>
			<div class="flex flex-col flex-wrap">
				{#each classes as cls (cls.id)}
					<a
						href={resolve(`/group/${cls.id}`)}
						class="border-b border-gray-200 pt-4 pb-4 transition-all duration-300 hover:bg-gray-100 hover:pl-4"
					>
						<div>
							<div class="flex flex-row gap-1">
								<h4 class="eyebrow eyebrow-dark shrink-0">
									{cls.institution?.name || 'Unknown Institution'}
								</h4>
								<h4 class="eyebrow eyebrow-dark shrink-0">|</h4>
								<h4 class="eyebrow eyebrow-dark shrink truncate">
									{cls.term || 'Unknown Session'}
								</h4>
							</div>
							<div class="pt-2 pb-2 text-lg font-light">
								{cls.name || 'Unknown'}
							</div>
							<div class="pb-1 text-xs tracking-wide text-gray-400 uppercase">
								{dayjs.utc(cls.updated).fromNow()}
							</div>
						</div>
					</a>
				{/each}

				{#if classes.length === 0}
					<div>No groups found</div>
				{/if}
			</div>
		</div>
	</div>
</div>
