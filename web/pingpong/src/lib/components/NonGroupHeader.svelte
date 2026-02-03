<script lang="ts">
	import { resolve } from '$app/paths';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import { ArrowRightOutline } from 'flowbite-svelte-icons';

	type Endpoint = '/admin' | '/admin/lti' | '/admin/terms' | '/admin/institutions';
	export let title: string;
	export let redirectUrl: Endpoint | null = null;
	export let redirectName: string | null = null;
</script>

<PageHeader paddingClass="p-2 pt-3 pb-3 pr-4 flex flex-row shrink rounded-t-4xl">
	<h2 class="text-color-blue-dark-50 px-4 pt-4 pb-4 font-serif text-3xl font-bold" slot="left">
		{title}
	</h2>
	<div slot="right">
		{#if redirectUrl && redirectName}
			<a
				href={resolve(redirectUrl)}
				class="flex items-center gap-2 rounded-full bg-white p-2 px-4 text-sm font-medium text-blue-dark-50 transition-all hover:bg-blue-dark-40 hover:text-white"
				>{redirectName} <ArrowRightOutline size="md" class="text-orange" /></a
			>
		{/if}
	</div>
</PageHeader>
