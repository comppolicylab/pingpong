<script lang="ts">
	import PageHeader from '$lib/components/PageHeader.svelte';
	import {
		Heading,
		Input,
		Label,
		Helper,
		Spinner,
		P,
		Toggle,
		Button,
		Tooltip,
		Accordion,
		AccordionItem,
		Checkbox
	} from 'flowbite-svelte';
	import dayjs from 'dayjs';
	import * as api from '$lib/api';
	import {
		BellActiveAltSolid,
		CogOutline,
		QuestionCircleOutline,
		TrashBinSolid
	} from 'flowbite-svelte-icons';
	import { sadToast, happyToast } from '$lib/toast';
	import { invalidateAll } from '$app/navigation';

	export let data;

	$: activitySubscription = data.subscriptions || [];
	$: eligibleSubscriptions = activitySubscription.filter(
		(sub) => !sub.class_private && sub.class_has_api_key
	);
	$: allSubscribed = eligibleSubscriptions.every((sub) => sub.subscribed);
	$: noneSubscribed = eligibleSubscriptions.every((sub) => !sub.subscribed);
	$: dnaAcCreate = !!data.subscriptionOpts.dna_as_create || false;
	$: dnaAcJoin = !!data.subscriptionOpts.dna_as_join || false;
	$: sortedLogins =
		data.externalLogins.sort((a: api.ExternalLogin, b: api.ExternalLogin) => {
			const nameA = a.provider_obj.display_name ?? a.provider_obj.name;
			const nameB = b.provider_obj.display_name ?? b.provider_obj.name;

			if (nameA !== nameB) {
				return nameA.localeCompare(nameB);
			}

			return a.identifier.localeCompare(b.identifier);
		}) || [];
	const inputState = {
		first_name: {
			loading: false,
			error: ''
		},
		last_name: {
			loading: false,
			error: ''
		}
	};

	const saveField = (field: keyof typeof inputState) => async (event: Event) => {
		const target = event.target as HTMLInputElement | undefined;
		if (!target) {
			return;
		}
		const value = target.value.trim();
		if (!value) {
			return;
		}
		inputState[field].loading = true;
		inputState[field].error = '';
		const response = await api.updateUserInfo(fetch, { [field]: value });
		const expanded = api.expandResponse(response);
		if (expanded.error) {
			inputState[field].error = expanded.error.detail || 'Unknown error';
		} else {
			target.value = expanded.data[field]!;
		}
		inputState[field].loading = false;
	};

	const unsubscribeFromSummaries = async (classId: number, className: string) => {
		const result = await api.unsubscribeFromSummary(fetch, classId);
		const response = api.expandResponse(result);
		if (response.error) {
			sadToast(response.error.detail || 'An unknown error occurred');
		} else {
			happyToast(`Successfully unsubscribed from <b>${className}</b> Activity Summaries.`, 5000);
		}
		invalidateAll();
	};

	const unsubscribeFromAllSummaries = async () => {
		const result = await api.unsubscribeFromAllSummaries(fetch);
		const response = api.expandResponse(result);
		if (response.error) {
			sadToast(response.error.detail || 'An unknown error occurred');
		} else {
			happyToast(`Successfully unsubscribed from all Activity Summaries.`, 5000);
		}
		invalidateAll();
	};

	const subscribeToAllSummaries = async () => {
		const result = await api.subscribeToAllSummaries(fetch);
		const response = api.expandResponse(result);
		if (response.error) {
			sadToast(response.error.detail || 'An unknown error occurred');
		} else {
			happyToast(`Successfully subscribed to all Activity Summaries.`, 5000);
		}
		invalidateAll();
	};

	const subscribeToSummaries = async (classId: number, className: string) => {
		const result = await api.subscribeToSummary(fetch, classId);
		const response = api.expandResponse(result);
		if (response.error) {
			sadToast(response.error.detail || 'An unknown error occurred');
		} else {
			happyToast(`Successfully subscribed to <b>${className}</b> Activity Summaries.`, 5000);
		}
		invalidateAll();
	};

	const handleSubscriptionChange = async (event: Event, classId: number, className: string) => {
		const target = event.target as HTMLInputElement;
		if (target.checked) {
			await subscribeToSummaries(classId, className);
		} else {
			await unsubscribeFromSummaries(classId, className);
		}
	};

	const handleDoNotAddWhenIJoinChange = async (event: Event) => {
		const target = event.target as HTMLInputElement;
		let result;
		if (target.checked) {
			result = await api.subscribeToAllSummariesAtJoin(fetch);
		} else {
			result = await api.unsubscribeFromAllSummariesAtJoin(fetch);
		}
		if (result) {
			const response = api.expandResponse(result);
			if (response.error) {
				sadToast(response.error.detail || 'An unknown error occurred');
				invalidateAll();
			} else {
				happyToast(`Successfully changed your Activity Summaries preferences.`, 3000);
			}
		}
	};

	const handleDoNotAddWhenICreateChange = async (event: Event) => {
		const target = event.target as HTMLInputElement;
		let result;
		if (target.checked) {
			result = await api.subscribeToAllSummariesAtCreate(fetch);
		} else {
			result = await api.unsubscribeFromAllSummariesAtCreate(fetch);
		}
		if (result) {
			const response = api.expandResponse(result);
			if (response.error) {
				sadToast(response.error.detail || 'An unknown error occurred');
				invalidateAll();
			} else {
				happyToast(`Successfully changed your Activity Summaries preferences.`, 3000);
			}
		}
	};
</script>

<div class="relative flex h-full w-full flex-col">
	<PageHeader>
		<h2 class="text-color-blue-dark-50 px-4 py-3 font-serif text-3xl font-bold" slot="left">
			Your Profile
		</h2>
	</PageHeader>
	<div class="h-full w-full overflow-y-auto p-12">
		<div class="mb-4 flex flex-row flex-wrap items-center justify-between gap-y-4">
			<Heading
				tag="h2"
				class="text-dark-blue-40 mr-5 max-w-max shrink-0 font-serif text-3xl font-medium"
				>Personal Information</Heading
			>
		</div>
		<div class="flex flex-col gap-4">
			<P>
				Manage your personal information used across PingPong. This information helps identify you
				to other users and moderators.
			</P>
			<div class="rounded-2xl bg-gray-100 p-6">
				<div class="grid grid-cols-1 gap-4 md:grid-cols-2">
					<div class="rounded-xl bg-white p-4 shadow-xs">
						<Label
							class="text-base mb-2 font-medium"
							for="firstName"
							color={inputState.first_name.error ? 'red' : undefined}>First Name</Label
						>
						<Input
							name="firstName"
							color={inputState.first_name.error ? 'red' : 'base'}
							value={data.me.user?.first_name}
							onchange={saveField('first_name')}
						>
							<div slot="right" class={inputState.first_name.loading ? '' : 'hidden'}>
								<Spinner size="4" color="green" />
							</div>
						</Input>
						{#if inputState.first_name.error}
							<Helper color="red" class="mt-2">
								<p>{inputState.first_name.error}</p>
							</Helper>
						{/if}
					</div>

					<div class="rounded-xl bg-white p-4 shadow-xs">
						<Label
							class="text-base mb-2 font-medium"
							for="lastName"
							color={inputState.last_name.error ? 'red' : undefined}>Last Name</Label
						>
						<Input
							name="lastName"
							color={inputState.last_name.error ? 'red' : 'base'}
							value={data.me.user?.last_name}
							onchange={saveField('last_name')}
						>
							<div slot="right" class={inputState.last_name.loading ? '' : 'hidden'}>
								<Spinner size="4" color="green" />
							</div>
						</Input>
						{#if inputState.last_name.error}
							<Helper color="red" class="mt-2">
								<p>{inputState.last_name.error}</p>
							</Helper>
						{/if}
					</div>

					<div class="rounded-xl bg-white p-4 shadow-xs">
						<div class="flex flex-col gap-2">
							<div class="flex flex-row items-center gap-2">
								<span class="font-medium">Primary Email</span>
								<div>
									<QuestionCircleOutline color="gray" />
									<Tooltip
										type="custom"
										arrow={false}
										class="z-10 flex max-w-xs flex-row overflow-y-auto bg-gray-900 px-3 py-2 text-sm font-light text-wrap text-white"
									>
										<div class="whitespace-normal normal-case">
											<p>Changing your primary email address is not currently supported.</p>
										</div>
									</Tooltip>
								</div>
							</div>
							<p class="text-gray-600">{data.me.user?.email || 'Unknown'}</p>
						</div>
					</div>
				</div>
			</div>
		</div>

		<div class="mt-12 mb-4 flex flex-row flex-wrap items-center justify-between gap-y-4">
			<Heading
				tag="h2"
				class="text-dark-blue-40 mr-5 max-w-max shrink-0 font-serif text-3xl font-medium"
				>External Logins</Heading
			>
		</div>
		<div class="flex flex-col gap-4">
			<P>
				PingPong supports log in and user syncing functionality with a number of External Login
				Providers. Some External Logins might offer additional options for logging in to PingPong or
				joining a Group.
			</P>
			{#if sortedLogins}
				<div class="w-full">
					<div class="rounded-2xl bg-gray-100 p-6">
						<div class="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
							{#each sortedLogins as login (login.id)}
								<div class="flex flex-col rounded-xl bg-white p-4 shadow-xs">
									<div class="mb-2 flex items-center gap-3">
										<div class="flex items-center gap-2">
											<span class="font-medium">
												{login.provider_obj.display_name || login.provider_obj.name}
											</span>
											{#if login.provider_obj.description}
												<div class="relative">
													<QuestionCircleOutline color="gray" />
													<Tooltip
														type="custom"
														arrow={false}
														class="z-10 flex w-64 flex-row bg-gray-900 px-3 py-2 text-sm font-light text-wrap text-white"
													>
														<div class="whitespace-normal normal-case">
															<p>{login.provider_obj.description}</p>
														</div>
													</Tooltip>
												</div>
											{/if}
										</div>
									</div>
									<div class="font-mono text-sm break-all text-gray-600">
										{login.identifier}
									</div>
								</div>
							{/each}
						</div>
					</div>
				</div>
			{/if}
		</div>

		{#if activitySubscription.length > 0}
			<div class="mt-14 mb-4 flex flex-row flex-wrap items-center justify-between gap-y-4">
				<Heading
					tag="h2"
					class="text-dark-blue-40 mr-5 max-w-max shrink-0 font-serif text-3xl font-medium"
					>Activity Summary Subscriptions</Heading
				>
				<div class="flex flex-row gap-2 gap-y-2">
					{#if !allSubscribed}
						<Button
							pill
							size="sm"
							class="flex flex-row gap-2 border border-solid border-blue-dark-40 bg-white text-blue-dark-40 hover:bg-blue-dark-40 hover:text-white"
							onclick={subscribeToAllSummaries}><BellActiveAltSolid />Subscribe to all</Button
						>
					{/if}
					{#if !noneSubscribed}
						<Button
							pill
							size="sm"
							class="flex flex-row gap-2 border border-solid border-blue-dark-40 bg-white text-blue-dark-40 hover:bg-blue-dark-40 hover:text-white"
							onclick={unsubscribeFromAllSummaries}><TrashBinSolid />Unsubscribe from all</Button
						>
					{/if}
				</div>
			</div>
			<div class="flex flex-col gap-4">
				<P>
					PingPong will gather all thread activity in a Group and email an AI-generated summary with
					relevant thread links to all Moderators at the end of each week. You will receive an
					Activity Summary for each Group you are subscribed to. <b
						>You won't receive Activity Summaries for Groups with no activity.</b
					>
				</P>
				<div class="rounded-2xl bg-gray-100 p-6">
					<div class="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
						{#each activitySubscription as subscription (subscription.class_id)}
							<div class="flex flex-col justify-between rounded-xl bg-white p-4 shadow-xs">
								<div class="mb-4 flex flex-col gap-2">
									<div class="text-lg font-medium text-blue-dark-40">{subscription.class_name}</div>
									<div class="text-sm text-gray-600">
										{#if subscription.class_private}
											<div class="flex flex-row items-center justify-between gap-2">
												<span class="text-xs font-medium text-gray-500 uppercase"
													>Ineligible: Private Group</span
												>
												<div>
													<QuestionCircleOutline color="gray" />
													<Tooltip
														type="custom"
														arrow={false}
														class="z-10 flex max-w-xs flex-row overflow-y-auto bg-gray-900 px-3 py-2 text-sm font-light text-wrap text-white"
													>
														<div class="whitespace-normal">
															<p>Activity Summaries are unavailable for private groups.</p>
														</div>
													</Tooltip>
												</div>
											</div>
										{:else if subscription.last_summary_empty}
											<div class="flex flex-col gap-1">
												<span class="text-xs font-medium text-gray-500 uppercase">Last summary</span
												>
												<div class="flex flex-row items-center gap-1">
													<span class="text-gray-700"
														>{subscription.last_email_sent
															? dayjs(subscription.last_email_sent).toString()
															: 'Never'}</span
													>
													<div>
														<QuestionCircleOutline color="gray" />
														<Tooltip
															type="custom"
															arrow={false}
															class="z-10 flex max-w-xs flex-row overflow-y-auto bg-gray-900 px-3 py-2 text-sm font-light text-wrap text-white"
														>
															<div class="whitespace-normal">
																<p>
																	We didn't send an Activity Summary for this Group last time
																	because there was no recent activity.
																</p>
															</div>
														</Tooltip>
													</div>
												</div>
											</div>
										{:else if !subscription.class_has_api_key}
											<div class="flex flex-row items-center justify-between gap-2">
												<span class="text-xs font-medium text-gray-500 uppercase"
													>Ineligible: No Billing Information</span
												>
												<div>
													<QuestionCircleOutline color="gray" />
													<Tooltip
														type="custom"
														arrow={false}
														class="z-10 flex max-w-xs flex-row overflow-y-auto bg-gray-900 px-3 py-2 text-sm font-light text-wrap text-white"
													>
														<div class="whitespace-normal">
															<p>
																Activity Summaries are unavailable for Groups with no billing
																information. Add a billing method and an Assistant to enable
																Activity Summaries.
															</p>
														</div>
													</Tooltip>
												</div>
											</div>
										{:else}
											<div class="flex flex-col gap-1">
												<span class="text-xs font-medium text-gray-500 uppercase">Last summary</span
												>
												<span class="text-gray-700"
													>{subscription.last_email_sent
														? dayjs(subscription.last_email_sent).toString()
														: 'Never'}</span
												>
											</div>
										{/if}
									</div>
								</div>
								{#if !subscription.class_private && subscription.class_has_api_key}
									<div class="flex items-center justify-between">
										<span class="text-sm text-gray-600">Receive summaries</span>
										<Toggle
											color="blue"
											checked={subscription.subscribed}
											onchange={(event) =>
												handleSubscriptionChange(
													event,
													subscription.class_id,
													subscription.class_name
												)}
										/>
									</div>
								{/if}
							</div>
						{/each}
					</div>
				</div>
			</div>
			<div class="my-5 w-full">
				<Accordion>
					<AccordionItem
						defaultClass="px-6 py-4 flex items-center justify-between w-full font-medium text-left group-first:rounded-t-none border-gray-200 dark:border-gray-700"
					>
						<span slot="header"
							><div class="flex flex-row items-center space-x-2 py-0">
								<div><CogOutline size="md" strokeWidth="2" /></div>
								<div class="text-sm">Advanced Options</div>
							</div></span
						>
						<div class="flex flex-col gap-4 px-1">
							<P class="text-base text-gray-600"
								>Manage additional settings about your Activity Summary subscriptions. These
								settings will apply for new Groups you create or join.</P
							>

							<div class="rounded-xl bg-gray-100 p-4">
								<div class="flex flex-col gap-3">
									<Checkbox
										id="dnaAcCreate"
										class="text-base font-normal"
										color="blue"
										checked={dnaAcCreate}
										onchange={handleDoNotAddWhenICreateChange}
										><b>Do not add</b>&nbsp;an Activity Subscription for new groups I create.</Checkbox
									>
									<Checkbox
										id="dnaAcJoin"
										class="text-base font-normal"
										color="blue"
										checked={dnaAcJoin}
										onchange={handleDoNotAddWhenIJoinChange}
										><b>Do not add</b>&nbsp;an Activity Subscription for new groups I join.</Checkbox
									>
								</div>
							</div>
						</div>
					</AccordionItem>
				</Accordion>
			</div>
		{/if}
	</div>
</div>
