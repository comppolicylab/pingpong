<script lang="ts">
	import * as Alert from '$lib/components/ui/alert/index.js';
	import * as Card from '$lib/components/ui/card/index.js';
	import { Badge } from '$lib/components/ui/badge/index.js';
	import { Input } from '$lib/components/ui/input/index.js';
	import { Label } from '$lib/components/ui/label';
	import { Textarea } from '$lib/components/ui/textarea/index.js';
	import Info from '@lucide/svelte/icons/info';
	import DataTable from '$lib/components/classes-table/data-table.svelte';
	import { columns } from '$lib/components/classes-table/columns.js';

	let { data } = $props();
</script>

<div class="flex flex-col gap-4">
	<div class="grid grid-cols-2 gap-4">
		<Card.Root>
			<Card.Header>
				<Card.Title>Personal Details</Card.Title>
				<Card.Description
					>Your personal information we received when you completed the application to participate
					in the study.</Card.Description
				>
			</Card.Header>
			<Card.Content>
				<div class="grid grid-cols-2 gap-6">
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
						<Label for="institution">Honorarium Status</Label>

						{#if data.instructor?.honorarium_status === 'Yes'}
							<Badge variant="outline" class="border-green-700/40 text-sm  dark:border-lime-500/80">
								<span class="text-green-800/90 dark:text-lime-400/90">Can receive honorarium</span>
							</Badge>
						{:else if data.instructor?.honorarium_status === 'No'}
							<Badge variant="outline" class="border-stone-950/40 text-sm dark:border-stone-300/70">
								<span class="text-stone-800/90 dark:text-stone-200/90"
									>Cannot receive honorarium</span
								>
							</Badge>
						{:else}
							<Badge
								variant="outline"
								class="border-amber-800/40 text-sm dark:border-yellow-500/70"
							>
								<span class="text-amber-700/90 dark:text-yellow-400/90"
									>Unsure: We'll follow up</span
								>
							</Badge>
						{/if}
						<p class="text-sm text-muted-foreground">
							This status reflects whether you can receive an honorarium. Eligibility for honorarium
							payments will be determined during the study.
						</p>
					</div>
					<div class="col-span-2 flex w-full flex-col gap-2.5">
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
			</Card.Content>
		</Card.Root>

		<Alert.Root class="self-start">
			<Info />
			<Alert.Title class="line-clamp-none tracking-normal"
				>Welcome to your new PingPong College Study Dashboard!</Alert.Title
			>
			<Alert.Description>
				<p>
					You'll soon be able to edit your personal and course details below. In the meantime,
					please email <a
						href="mailto:support@pingpong-hks.atlassian.net"
						class="text-nowrap text-primary underline underline-offset-4 hover:text-primary/80"
						>support@pingpong-hks.atlassian.net
					</a> if any of the information listed on this dashboard is incorrect.
				</p>
			</Alert.Description>
		</Alert.Root>
	</div>

	<h2 class="mt-4 text-xl font-semibold">Your Classes</h2>
	<DataTable data={data.courses} {columns} />
</div>
