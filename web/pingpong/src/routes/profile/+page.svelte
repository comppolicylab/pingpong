<script lang="ts">
  import PageHeader from '$lib/components/PageHeader.svelte';
  import { Heading, Input, Label, Helper, Spinner } from 'flowbite-svelte';
  import dayjs from 'dayjs';
  import * as api from '$lib/api';

  export let data;

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
</script>

<div class="flex flex-col gap-8 about h-full overflow-y-auto">
  <PageHeader>
    <h2 class="text-3xl text-color-blue-dark-50 font-serif font-bold px-4 py-3" slot="left">
      Profile
    </h2>
  </PageHeader>

  <div class="mx-12 flex gap-12 flex-wrap">
    <div>
      <Label for="firstName" color={inputState.first_name.error ? 'red' : undefined}
        >First Name</Label
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
      <Label for="lastName" color={inputState.last_name.error ? 'red' : undefined}>Last Name</Label>
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

  <div class="mx-12">
    <Heading tag="h3">Email</Heading>
    <p>{data.me.user?.email || 'Unknown'}</p>
  </div>

  <div class="mx-12">
    <Heading tag="h3">State</Heading>
    <p>{data.me.user?.state || 'Unknown'}</p>
  </div>

  <div class="mx-12">
    <Heading tag="h3">Account created</Heading>
    <p>{data.me.user?.created ? dayjs(data.me.user.created).toString() : 'Unknown'}</p>
  </div>
</div>
