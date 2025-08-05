<script lang="ts">
	import { Button } from '$lib/components/ui/button/index.js';
	import * as Card from '$lib/components/ui/card/index.js';
	import { Label } from '$lib/components/ui/label/index.js';
	import { Input } from '$lib/components/ui/input/index.js';
	import { cn } from '$lib/utils.js';
	import type { HTMLAttributes } from 'svelte/elements';

	let { class: className, ...restProps }: HTMLAttributes<HTMLDivElement> = $props();

	const id = $props.id();

	async function handleSubmit(event: Event) {
		event.preventDefault();
		const formData = new FormData(event.target as HTMLFormElement);
		const email = formData.get('email') as string;

		// Perform login action
		console.log('Logging in with email:', email);
	}
</script>

<div class={cn('flex flex-col gap-6', className)} {...restProps}>
	<Card.Root>
		<Card.Header class="text-center">
			<Card.Title class="text-xl">Welcome back</Card.Title>
			<Card.Description>Login with your institutional email</Card.Description>
		</Card.Header>
		<Card.Content>
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
							/>
						</div>
						<Button type="submit" class="w-full">Login</Button>
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
		</Card.Content>
	</Card.Root>
</div>
