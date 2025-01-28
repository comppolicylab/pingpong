<script lang="ts">
  import PageHeader from '$lib/components/PageHeader.svelte';
  import {
    Heading,
    Input,
    Label,
    Helper,
    Spinner,
    Table,
    TableBody,
    TableBodyCell,
    TableBodyRow,
    TableHeadCell,
    TableHead,
    P,
    Toggle,
    Button
  } from 'flowbite-svelte';
  import dayjs from 'dayjs';
  import * as api from '$lib/api';
  import { BellActiveAltSolid, TrashBinSolid } from 'flowbite-svelte-icons';
  import { sadToast, happyToast } from '$lib/toast';
  import { invalidateAll } from '$app/navigation';

  export let data;

  $: activitySubscription = data.subscriptions || [];
  $: allSubscribed = activitySubscription.every((sub) => sub.subscribed);
  $: noneSubscribed = activitySubscription.every((sub) => !sub.subscribed);

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
      invalidateAll();
    }
  };

  const unsubscribeFromAllSummaries = async () => {
    const result = await api.unsubscribeFromAllSummaries(fetch);
    const response = api.expandResponse(result);
    if (response.error) {
      sadToast(response.error.detail || 'An unknown error occurred');
    } else {
      happyToast(`Successfully unsubscribed from all Activity Summaries.`, 5000);
      invalidateAll();
    }
  };

  const subscribeToAllSummaries = async () => {
    const result = await api.subscribeToAllSummaries(fetch);
    const response = api.expandResponse(result);
    if (response.error) {
      sadToast(response.error.detail || 'An unknown error occurred');
    } else {
      happyToast(`Successfully subscribed to all Activity Summaries.`, 5000);
      invalidateAll();
    }
  };

  const subscribeToSummaries = async (classId: number, className: string) => {
    const result = await api.subscribeToSummary(fetch, classId);
    const response = api.expandResponse(result);
    if (response.error) {
      sadToast(response.error.detail || 'An unknown error occurred');
    } else {
      happyToast(`Successfully subscribed to <b>${className}</b> Activity Summaries.`, 5000);
      invalidateAll();
    }
  };

  const handleSubscriptionChange = async (event: Event, classId: number, className: string) => {
    const target = event.target as HTMLInputElement;
    if (target.checked) {
      await subscribeToSummaries(classId, className);
    } else {
      await unsubscribeFromSummaries(classId, className);
    }
  };
</script>

<div class="relative h-full w-full flex flex-col">
  <PageHeader>
    <h2 class="text-3xl text-color-blue-dark-50 font-serif font-bold px-4 py-3" slot="left">
      Your Profile
    </h2>
  </PageHeader>
  <div class="h-full w-full overflow-y-auto p-12">
    <Heading tag="h2" class="text-3xl font-serif mb-4 font-medium text-dark-blue-40"
      >Personal Information</Heading
    >
    <div class="bg-gray-100 rounded-2xl p-8 gap-5 items-start flex flex-col">
      <div class="flex flex-row gap-12 flex-wrap">
        <div>
          <Label
            class="mb-1 font-serif text-xl font-bold"
            for="firstName"
            color={inputState.first_name.error ? 'red' : undefined}>First Name</Label
          >
          <Input
            name="firstName"
            color={inputState.first_name.error ? 'red' : undefined}
            value={data.me.user?.first_name}
            on:change={saveField('first_name')}
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
        <div>
          <Label
            class="mb-1 font-serif text-xl font-bold"
            for="lastName"
            color={inputState.last_name.error ? 'red' : undefined}>Last Name</Label
          >
          <Input
            name="lastName"
            color={inputState.last_name.error ? 'red' : undefined}
            value={data.me.user?.last_name}
            on:change={saveField('last_name')}
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
      </div>

      <div>
        <div class="mb-5">
          <Heading tag="h3" class="font-serif text-xl">Email</Heading>
          <p>{data.me.user?.email || 'Unknown'}</p>
        </div>

        <div class="mb-5">
          <Heading tag="h3" class="font-serif text-xl">State</Heading>
          <p>{data.me.user?.state || 'Unknown'}</p>
        </div>

        <div class="">
          <Heading tag="h3" class="font-serif text-xl">Account created</Heading>
          <p>{data.me.user?.created ? dayjs(data.me.user.created).toString() : 'Unknown'}</p>
        </div>
      </div>
    </div>

    {#if activitySubscription.length > 0}
      <div class="flex flex-row flex-wrap justify-between mt-12 mb-4 items-center gap-y-4">
        <Heading
          tag="h2"
          class="text-3xl font-serif font-medium text-dark-blue-40 shrink-0 max-w-max mr-5"
          >Activity Summary Subscriptions</Heading
        >
        <div class="flex flex-row gap-2 gap-y-2">
          {#if !allSubscribed}
            <Button
              pill
              size="sm"
              class="flex flex-row gap-2 bg-white text-blue-dark-40 border-solid border border-blue-dark-40 hover:text-white hover:bg-blue-dark-40"
              on:click={subscribeToAllSummaries}><BellActiveAltSolid />Subscribe to all</Button
            >
          {/if}
          {#if !noneSubscribed}
            <Button
              pill
              size="sm"
              class="flex flex-row gap-2 bg-white text-blue-dark-40 border-solid border border-blue-dark-40 hover:text-white hover:bg-blue-dark-40"
              on:click={unsubscribeFromAllSummaries}><TrashBinSolid />Unsubscribe from all</Button
            >
          {/if}
        </div>
      </div>
      <div class="flex flex-col gap-4">
        <P>
          PingPong will gather all thread activity in a Group and email an AI-generated summary with
          relevant thread links to all Moderators at the end of each week. You will receive an
          Activity Summary for each Group you are subscribed to.
        </P>
        <Table>
          <TableHead class="bg-blue-light-40 p-1 text-blue-dark-50 tracking-wide rounded-2xl">
            <TableHeadCell>Class Name</TableHeadCell>
            <TableHeadCell>Last Activity Summary Sent At</TableHeadCell>
            <TableHeadCell>Receive Activity Summaries</TableHeadCell>
          </TableHead>
          <TableBody>
            {#each activitySubscription as subscription}
              <TableBodyRow>
                <TableBodyCell class="font-light">{subscription.class_name}</TableBodyCell>
                <TableBodyCell class="font-light"
                  >{subscription.last_email_sent
                    ? dayjs(subscription.last_email_sent).toString()
                    : 'Never'}</TableBodyCell
                >
                <TableBodyCell>
                  <Toggle
                    color="blue"
                    checked={subscription.subscribed}
                    on:change={(event) =>
                      handleSubscriptionChange(
                        event,
                        subscription.class_id,
                        subscription.class_name
                      )}
                  />
                </TableBodyCell>
              </TableBodyRow>
            {/each}
          </TableBody>
        </Table>
      </div>
    {/if}
  </div>
</div>
