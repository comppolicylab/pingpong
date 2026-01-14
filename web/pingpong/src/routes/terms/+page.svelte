<script lang="ts">
	import { Button, Heading } from 'flowbite-svelte';
	import * as api from '$lib/api';
	import { happyToast, sadToast } from '$lib/toast';
	import { resolve } from '$app/paths';
	import { goto } from '$app/navigation';
	import PingPongLogo from '$lib/components/PingPongLogo.svelte';
	import { page } from '$app/stores';
	import SanitizeFlowbite from '$lib/components/SanitizeFlowbite.svelte';
	import { loading } from '$lib/stores/general.js';

	export let data;

	$: agreement = data.agreement;
	$: policyId = data.policyId;

	const logout = async () => {
		await goto(resolve('/logout'));
	};

	const goToDestination = async () => {
		$loading = true;
		const destination = $page.url.searchParams.get('forward') || '/';
		// eslint-disable-next-line svelte/no-navigation-without-resolve
		await goto(destination);
		$loading = false;
	};

	const acceptAgreement = async () => {
		if (!agreement || !policyId) {
			return;
		}
		$loading = true;
		const response = await api.acceptAgreementByPolicyId(fetch, policyId).then(api.expandResponse);
		if (response.error) {
			$loading = false;
			return sadToast(response.error.detail || 'Unknown error accepting agreement');
		}
		happyToast('Agreement accepted. Redirecting...');
		await goToDestination();
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
				{#if agreement !== null}
					<SanitizeFlowbite html={agreement?.body} />
					<div class="mt-4 flex flex-row justify-end gap-4 text-center">
						<Button
							class="rounded-full border border-blue-dark-40 bg-white text-blue-dark-40 hover:bg-blue-dark-40 hover:text-white"
							type="button"
							onclick={logout}
							disabled={$loading}>Exit PingPong</Button
						>
						<Button
							type="submit"
							class="rounded-full bg-orange text-white hover:bg-orange-dark"
							onclick={acceptAgreement}
							disabled={$loading}>Accept</Button
						>
					</div>
				{:else}
					<p class="text-lg text-gray-800">No agreement found.</p>
					<div class="mt-4 flex flex-row justify-end gap-4 text-center">
						<Button
							class="items w-fit rounded-full border border-blue-dark-40 bg-white text-blue-dark-40 hover:bg-blue-dark-40 hover:text-white"
							type="button"
							onclick={goToDestination}
							disabled={$loading}>Continue to PingPong</Button
						>
					</div>
				{/if}
			</div>
		</div>
	</div>
</div>
