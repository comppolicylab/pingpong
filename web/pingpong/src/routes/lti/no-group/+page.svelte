<script lang="ts">
	import { Button, Heading } from 'flowbite-svelte';
	import { goto } from '$app/navigation';
	import PingPongLogo from '$lib/components/PingPongLogo.svelte';
	import { loading } from '$lib/stores/general.js';
	import { resolve } from '$app/paths';

	const continueToPingPong = async () => {
		$loading = true;
		await goto(resolve('/'));
		$loading = false;
	};
</script>

<div class="v-screen flex h-[calc(100dvh-3rem)] items-center justify-center">
	<div class="flex w-11/12 max-w-2xl flex-col overflow-hidden rounded-4xl lg:w-7/12">
		<header class="bg-blue-dark-40 px-12 py-8">
			<Heading tag="h1" class="logo w-full text-center"><PingPongLogo size="full" /></Heading>
		</header>
		<div class="bg-white px-12 py-8">
			<div class="flex flex-col gap-4">
				<div class="mb-2 w-full text-3xl font-medium">This course isn't on PingPong yet.</div>
				<div class="flex w-full flex-col gap-4">
					<p class="text-md">
						Your instructor hasn&apos;t linked this Canvas course to a PingPong group, so there
						isn&apos;t a class space to enter.
					</p>
					<p class="text-md">
						Please ask your instructor to complete the setup. In the meantime, you can continue to
						the main PingPong page.
					</p>
				</div>
				<div class="mt-4 flex flex-row justify-end gap-4 text-center">
					<Button
						type="button"
						class="rounded-full bg-orange text-white hover:bg-orange-dark"
						onclick={continueToPingPong}
						disabled={$loading}>Continue</Button
					>
				</div>
			</div>
		</div>
	</div>
</div>
