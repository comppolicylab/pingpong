<script lang="ts">
	import PingPongLogo from '$lib/components/PingPongLogo.svelte';
	import { Heading } from 'flowbite-svelte';
	import { onMount } from 'svelte';
	import { ltiHeaderComponent, ltiHeaderProps } from '$lib/stores/ltiHeader';

	onMount(() => {
		ltiHeaderComponent.set(null);
		ltiHeaderProps.set({});
	});
</script>

<div class="v-screen flex h-[calc(100dvh-3rem)] items-center justify-center">
	<div class="flex w-11/12 max-w-2xl flex-col overflow-hidden rounded-4xl lg:w-6/12">
		<header class="bg-blue-dark-40 px-5 py-8 md:px-12">
			<Heading tag="h1" class="logo w-full text-center"><PingPongLogo size="full" /></Heading>
		</header>
		<div class="bg-white px-5 py-16 md:px-12">
			<div class="mb-2 text-center font-serif text-4xl font-bold text-blue-dark-50">
				We're logging you out...
			</div>
			<div class="text-center text-lg">Please wait a moment.</div>
		</div>
	</div>
</div>
