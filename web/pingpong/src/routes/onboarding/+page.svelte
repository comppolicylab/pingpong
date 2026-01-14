<script lang="ts">
	import { page } from '$app/stores';
	import { Input, Button, Heading } from 'flowbite-svelte';
	import * as api from '$lib/api';
	import { happyToast, sadToast } from '$lib/toast';
	import { goto } from '$app/navigation';
	import PingPongLogo from '$lib/components/PingPongLogo.svelte';

	export let data;

	let loading = false;

	const saveName = async (event: SubmitEvent) => {
		event.preventDefault();
		const form = event.target as HTMLFormElement | undefined;
		if (!form) {
			return;
		}
		loading = true;
		const formData = new FormData(form);
		const first_name = formData.get('firstName')?.toString();
		const last_name = formData.get('lastName')?.toString();

		if (!first_name || !last_name) {
			loading = false;
			return sadToast('Please enter your first and last name');
		}

		const response = await api.updateUserInfo(fetch, { first_name, last_name });
		const expanded = api.expandResponse(response);
		if (expanded.error) {
			sadToast(`Failed to profile information: ${expanded.error.detail}`);
		} else {
			happyToast('Profile information saved');
			// Get `forward` parameter from URL
			const destination = $page.url.searchParams.get('forward') || '/';
			// eslint-disable-next-line svelte/no-navigation-without-resolve
			await goto(destination, { invalidateAll: true });
		}
		loading = false;
	};
</script>

<div class="v-screen flex h-[calc(100dvh-3rem)] items-center justify-center">
	<div class="flex w-11/12 max-w-2xl flex-col overflow-hidden rounded-4xl lg:w-6/12">
		<header class="bg-blue-dark-40 px-12 py-8">
			<Heading tag="h1" class="logo w-full text-center"><PingPongLogo size="full" /></Heading>
		</header>
		<div class="bg-white px-8 py-8">
			<form onsubmit={saveName}>
				<section class="flex flex-col gap-2">
					<div class="text-md w-full">
						Welcome, {data.me.user?.email || 'Unknown'}.
					</div>
					<div class="mb-6 w-full text-xs">Please enter your name to continue.</div>
					<div>
						<Input
							type="text"
							placeholder="First name / given name"
							name="firstName"
							value={data.me.user?.first_name || ''}
							disabled={loading}
						/>
					</div>
					<div>
						<Input
							type="text"
							placeholder="Surname / family name"
							name="lastName"
							value={data.me.user?.last_name || ''}
							disabled={loading}
						/>
					</div>
					<div class="mt-4 flex justify-end text-center">
						<Button
							type="submit"
							class="rounded-full bg-orange text-white hover:bg-orange-dark"
							disabled={loading}>Continue to PingPong</Button
						>
					</div>
				</section>
			</form>
		</div>
	</div>
</div>
