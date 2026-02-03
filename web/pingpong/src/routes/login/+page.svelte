<script lang="ts">
	import PingPongLogo from '$lib/components/PingPongLogo.svelte';
	import { Button, InputAddon, Input, Heading, ButtonGroup } from 'flowbite-svelte';
	import { EnvelopeSolid } from 'flowbite-svelte-icons';
	import { writable } from 'svelte/store';
	import { sadToast } from '$lib/toast';
	import * as api from '$lib/api';
	import { page } from '$app/stores';
	import { onMount } from 'svelte';
	import { ltiHeaderState } from '$lib/stores/ltiHeader';

	onMount(() => {
		ltiHeaderState.set({ kind: 'none' });
	});

	export let form;
	const forward = $page.url.searchParams.get('forward') || '/';
	const expired = $page.url.searchParams.get('expired') === 'true' || false;
	const new_link = $page.url.searchParams.get('new_link') === 'true' || false;
	const loggingIn = writable(false);
	const success = writable(false);

	let email = form?.email ?? '';

	const loginWithMagicLink = async (evt: SubmitEvent) => {
		evt.preventDefault();
		loggingIn.set(true);

		const form = evt.target as HTMLFormElement;
		const formData = new FormData(form);
		const d = Object.fromEntries(formData.entries());

		const email = d.email?.toString();
		if (!email) {
			loggingIn.set(false);
			sadToast('Please provide a valid email address');
			return;
		}

		const result = await api.loginWithMagicLink(fetch, email, forward);
		if (result.$status < 300) {
			success.set(true);
			loggingIn.set(false);
		} else {
			sadToast(result.detail?.toString() || 'Could not log in');
			loggingIn.set(false);
		}
	};
</script>

<div class="v-screen flex h-[calc(100dvh-3rem)] items-center justify-center">
	<div class="flex w-11/12 max-w-2xl flex-col overflow-hidden rounded-4xl lg:w-6/12">
		<header class="bg-blue-dark-40 px-5 py-8 md:px-12">
			<Heading tag="h1" class="logo w-full text-center"><PingPongLogo size="full" /></Heading>
		</header>
		<div class="bg-white px-5 pt-10 pb-16 md:px-12">
			{#if $success}
				<div class="mt-5 mb-2 text-center font-serif text-4xl font-bold text-blue-dark-50">
					Success!
				</div>
				<div class="text-center text-lg">Follow the link in your email to finish signing in.</div>
			{:else if new_link}
				<div class="mt-5 mb-4 text-center font-serif text-4xl font-bold text-blue-dark-50">
					Let's try this again.
				</div>
				<div class="text-center text-lg">
					This log-in link isn't currently valid.<br />We sent a new link to your email.
				</div>
			{:else}
				<div class="mb-6">
					{#if expired}
						<div class="mb-2 text-center font-serif text-4xl font-bold text-blue-dark-50">
							Let's try this again.
						</div>
						<div class="text-center text-lg">
							This log-in link isn't currently valid.<br />Try logging in with your school email
							address again.
						</div>
					{:else}
						<div class="mb-2 text-center font-serif text-4xl font-bold text-blue-dark-50">
							{form?.error ? 'We could not sign you in.' : 'Welcome to PingPong'}
						</div>
						<div class="text-center text-lg">
							{form?.error
								? 'Please make sure you are using the correct email address and try again.'
								: 'Use your school email address to log in.'}
						</div>
					{/if}
				</div>
				<form onsubmit={loginWithMagicLink}>
					<ButtonGroup class="w-full rounded-full bg-blue-light-50 p-4 shadow-inner">
						<InputAddon class="rounded-none border-none bg-transparent text-blue-dark-30">
							<EnvelopeSolid />
						</InputAddon>
						<Input
							bind:value={email}
							readonly={$loggingIn || null}
							type="email"
							placeholder="you@school.edu"
							name="email"
							id="email"
							class="border-none bg-transparent text-base"
						></Input>
						<Button
							pill
							class="mr-2 rounded-full bg-orange-dark p-3 px-4 px-6 py-2 text-base text-white hover:bg-orange"
							type="submit"
							disabled={$loggingIn || !email}>Login</Button
						>
					</ButtonGroup>
				</form>
			{/if}
		</div>
	</div>
</div>
