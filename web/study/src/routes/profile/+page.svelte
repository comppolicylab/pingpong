<script lang="ts">
	import { Badge } from '$lib/components/ui/badge/index.js';
	import { Input } from '$lib/components/ui/input/index.js';
	import { Label } from '$lib/components/ui/label';
	import { Textarea } from '$lib/components/ui/textarea/index.js';
	import * as Alert from '$lib/components/ui/alert/index.js';
	import Info from '@lucide/svelte/icons/info';

	let { data } = $props();
</script>

<div class="flex flex-1 flex-col gap-1 px-4 py-10">
	<div class="flex flex-col gap-2">
		<h1 class="mx-auto w-full max-w-3xl scroll-m-20 text-4xl font-bold text-balance">Profile</h1>
		<p class="mx-auto w-full max-w-3xl scroll-m-20 text-base text-muted-foreground">
			Your personal information we received when you applied to participate in the study.
		</p>
	</div>

	<Alert.Root class="mx-auto mt-3 w-full max-w-3xl text-base">
		<Info />
		<Alert.Title class="line-clamp-none text-sm font-normal tracking-normal">
			Profile changes cannot be made on the website. Please email
			<a
				href="mailto:support@pingpong-hks.atlassian.net"
				class="text-primary underline underline-offset-4"
			>
				support@pingpong-hks.atlassian.net
			</a>
			to inform us of any updates.
		</Alert.Title>
	</Alert.Root>

	<div class="mx-auto w-full max-w-3xl space-y-5 pt-6">
		<div class="flex w-full flex-col gap-1.5">
			<Label for="first-name">First Name</Label>
			<Input
				type="text"
				id="first-name"
				placeholder="First Name"
				value={data.instructor?.first_name}
				disabled
				class="disabled:opacity-90"
			/>
		</div>

		<div class="flex w-full flex-col gap-1.5">
			<Label for="last-name">Last Name</Label>
			<Input
				type="text"
				id="last-name"
				placeholder="Last Name"
				value={data.instructor?.last_name}
				disabled
				class="disabled:opacity-90"
			/>
		</div>

		<div class="flex w-full flex-col gap-1.5">
			<Label for="email">Institutional Email</Label>
			<Input
				type="email"
				id="email"
				placeholder="Email"
				value={data.instructor?.academic_email}
				disabled
				class="disabled:opacity-90"
			/>
		</div>

		<div class="flex w-full flex-col gap-1.5">
			<Label for="email-2">Personal Email</Label>
			<Input
				type="email"
				id="email-2"
				placeholder="Email"
				value={data.instructor?.personal_email}
				disabled
				class="disabled:opacity-90"
			/>
		</div>

		<div class="flex w-full flex-col gap-1.5">
			<Label for="institution">Institution</Label>
			<Input
				type="text"
				id="institution"
				placeholder="Institution"
				value={data.instructor?.institution}
				disabled
				class="disabled:opacity-90"
			/>
		</div>

		<div class="flex w-full flex-col gap-2.5">
			<Label for="honorarium-status">Honorarium Status</Label>
			{#if data.instructor?.honorarium_status === 'Yes'}
				<Badge variant="outline" class="w-fit border-green-700/40 text-sm dark:border-lime-500/80">
					<span class="text-green-800/90 dark:text-lime-400/90">Can receive honorarium</span>
				</Badge>
			{:else if data.instructor?.honorarium_status === 'No'}
				<Badge variant="outline" class="w-fit border-stone-950/40 text-sm dark:border-stone-300/70">
					<span class="text-stone-800/90 dark:text-stone-200/90">Cannot receive honorarium</span>
				</Badge>
			{:else}
				<Badge
					variant="outline"
					class="w-fit border-amber-800/40 text-sm dark:border-yellow-500/70"
				>
					<span class="text-amber-700/90 dark:text-yellow-400/90">Unsure: We'll follow up</span>
				</Badge>
			{/if}
			<p class="text-sm text-muted-foreground">
				This status reflects whether you can receive an honorarium. Eligibility for honorarium
				payments will be determined during the study.
			</p>
		</div>

		<div class="flex w-full flex-col gap-2.5">
			<Label for="mailing">Mailing Address</Label>
			<Textarea
				id="mailing"
				placeholder="Mailing Address"
				value={data.instructor?.mailing_address}
				disabled
				class="disabled:opacity-90"
			/>
			<p class="text-sm text-muted-foreground">
				Your mailing address is only needed if you are eligible to receive an honorarium.
			</p>
		</div>
	</div>
</div>
