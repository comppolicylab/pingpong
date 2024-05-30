<script lang="ts">
  import PageHeader from '$lib/components/PageHeader.svelte';
  import { Heading } from 'flowbite-svelte';
  import dayjs from 'dayjs';

  export let data;
</script>

<div class="flex flex-col gap-8 about h-full overflow-y-auto">
  <PageHeader>
    <h2 class="text-3xl text-color-blue-dark-50 font-serif font-bold px-4 py-3" slot="left">
      Profile
    </h2>
  </PageHeader>

  <div class="mx-12 flex gap-12 flex-wrap">
    <div>
      <Heading tag="h3">First Name</Heading>
      <p>{data.me.user?.first_name || 'Unknown'}</p>
    </div>

    <div>
      <Heading tag="h3">Last Name</Heading>
      <p>{data.me.user?.last_name || 'Unknown'}</p>
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
