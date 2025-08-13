<script lang="ts">
	import { Button } from '$lib/components/ui/button/index.js';
	import * as Card from '$lib/components/ui/card/index.js';
	import { Label } from '$lib/components/ui/label/index.js';
	import { Input } from '$lib/components/ui/input/index.js';
	import { cn } from '$lib/utils.js';
	import type { HTMLAttributes } from 'svelte/elements';
	import { loginWithMagicLink } from '$lib/api/client';
	import { fail } from '@sveltejs/kit';
	import SpinnerIcon from '$lib/components/spinner.svelte';
	let { class: className, ...restProps }: HTMLAttributes<HTMLDivElement> = $props();
	import { page } from '$app/state';
	import { toast } from 'svelte-sonner';

	const forward = page.url.searchParams.get('forward') || '/';
	const expired = page.url.searchParams.get('expired') === 'true' || false;
	const new_link = page.url.searchParams.get('new_link') === 'true' || false;

	const id = $props.id();
	let emailSent = $state(false);
	let isLoading = $state(false);

	async function handleSubmit(event: Event) {
		event.preventDefault();
		isLoading = true;
		const formData = new FormData(event.target as HTMLFormElement);
		const email = formData.get('email') as string;

		if (!email) {
			return fail(400, { email, success: false, error: 'Missing email' });
		}

		const result = await loginWithMagicLink(fetch, email, forward);
		if (result.$status < 300) {
			emailSent = true;
		} else {
			toast.error(
				result.detail?.toString() ||
					'We faced an unexpected error. Please try again or contact the study administrator.',
				{
					duration: 10000
				}
			);
		}
		isLoading = false;
	}
</script>

<div class={cn('flex flex-col gap-6', className)} {...restProps}>
	<Card.Root>
		{#if !emailSent && !expired && !new_link}
			<Card.Header class="text-center">
				<Card.Title class="text-xl">Welcome back</Card.Title>
				<Card.Description>Login with your institutional email</Card.Description>
			</Card.Header>
		{:else if expired}
			<Card.Header class="text-center">
				<Card.Title class="text-xl">Let's try this again.</Card.Title>
				<Card.Description>
					The log-in link you used is no longer valid.<br />Try logging in with your institutional
					email address again.
				</Card.Description>
			</Card.Header>
		{/if}
		<Card.Content>
			{#if !emailSent && !new_link}
				<form onsubmit={handleSubmit}>
					<div class="grid gap-6">
						<div class="grid gap-6">
							<div class="grid gap-3">
								<Label for="email-{id}">Email</Label>
								<Input
									id="email-{id}"
									type="email"
									name="email"
									placeholder="name@example.edu"
									required
									disabled={isLoading}
								/>
							</div>
							<Button type="submit" class="w-full" disabled={isLoading}>
								{#if isLoading}
									<SpinnerIcon class="animate-spin" />
								{:else}
									Login
								{/if}
							</Button>
						</div>
						<div class="text-center text-sm">
							Not an instructor in the study?
							<a
								href="https://pingpong.hks.harvard.edu/eduaccess"
								target="_blank"
								class="underline underline-offset-4"
							>
								Sign up
							</a>
						</div>
					</div>
				</form>
			{:else if emailSent}
				<div class="flex flex-col gap-1">
					<div class="text-center text-lg font-semibold">Success!</div>
					<div class="text-center text-sm text-muted-foreground">
						Follow the link in your email to finish signing in.
					</div>
					<Button onclick={() => (emailSent = false)} class="mt-4">Back to login</Button>
				</div>
			{:else if new_link}
				<div class="flex flex-col gap-1">
					<div class="text-center text-lg font-semibold">Let's try this again.</div>
					<div class="text-center text-sm text-muted-foreground">
						The log-in link you used has expired.<br />We sent a new link to your email.
					</div>
					<Button onclick={() => (window.location.href = '/login')} class="mt-4"
						>Back to login</Button
					>
				</div>
			{/if}
		</Card.Content>
	</Card.Root>
</div>
