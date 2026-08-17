<script lang="ts">
	import { Button, Heading } from 'flowbite-svelte';
	import { page } from '$app/stores';
	import { resolve } from '$app/paths';
	import PingPongLogo from '$lib/components/PingPongLogo.svelte';

	$: classId = Number.parseInt($page.url.searchParams.get('class_id') || '', 10);
</script>

<div class="flex min-h-[100dvh] items-center justify-center bg-gray-50 p-6">
	<div class="w-full max-w-xl overflow-hidden rounded-3xl bg-white shadow-lg">
		<header class="bg-blue-dark-40 px-8 py-6">
			<Heading tag="h1" class="logo w-full text-center"><PingPongLogo size="full" /></Heading>
		</header>
		<div class="space-y-4 p-8 text-center">
			<Heading tag="h2" class="font-serif text-2xl font-medium text-blue-dark-50">
				Assistant unavailable
			</Heading>
			<p class="text-gray-600">
				The assistant selected for this Canvas link has been unpublished or deleted.
			</p>
			{#if Number.isInteger(classId) && classId > 0}
				<Button
					href={resolve(`/group/${classId}`)}
					class="bg-orange text-white hover:bg-orange-dark"
				>
					Open the PingPong group
				</Button>
			{/if}
		</div>
	</div>
</div>
