<script lang="ts">
  import dayjs from '$lib/time';
  import { page } from '$app/stores';
  import { Button, Select, Hr } from 'flowbite-svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import { updateSearch, getValue } from '$lib/urlstate';

  export let data;

  let institutionOptions: { value: string; name: string }[] = [];
  $: instSearch = parseInt($page.url.searchParams.get('institution_id') || '0', 10);
  $: {
    institutionOptions = [
      { value: '0', name: 'All' },
      ...data.institutions
        .sort((a, b) => a.name.localeCompare(b.name))
        .map((inst) => ({ value: `${inst.id}`, name: inst.name }))
    ];
  }
  $: classes = (data.classes || [])
    .filter((cls) => (instSearch ? cls.institution_id === instSearch : true))
    .sort((a, b) => a.name.localeCompare(b.name));
</script>

<div class="h-full w-full flex flex-col">
  <PageHeader>
    <h2 class="text-3xl text-color-blue-dark-50 font-serif font-bold px-4 pb-3 pt-6" slot="left">
      Admin
    </h2>
  </PageHeader>

  <!-- TODO: search is not yet fully supported. -->

  <div class="grid gap-12 p-12 sm:grid-cols-[2fr_1fr] min-h-0 grow shrink">
    <div class="sm:col-start-2 sm:col-end-3 overflow-y-auto">
      <div class="flex flex-col gap-4">
        <div>
          <label for="institution" class="text-xs uppercase tracking-wide block pb-2 pt-8"
            >Filter by <b>Institution</b></label
          >
          <Select
            items={institutionOptions}
            on:change={(e) => updateSearch('institution_id', getValue(e.target))}
            value={`${instSearch}`}
            name="institution"
          />
        </div>
        <div>
          <Button
            class="bg-orange text-white rounded-full hover:bg-orange-dark"
            href="/admin/createGroup">Create a new group</Button
          >
        </div>
        {#if data.statistics}
          <Hr />
          <div class="flex flex-col gap-2 mb-6">
            <span class="text-lg font-medium text-center uppercase mb-3">PingPong Stats</span>
            <div
              class="flex flex-col gap-2 bg-gold-light rounded-2xl px-8 pt-6 py-4 pb-6 text-center"
            >
              <span class="text-5xl font-light text-blue-dark-40">
                {data.statistics.institutions}
              </span>
              <span class="text-md font-medium uppercase text-blue-dark-50">Institutions</span>
            </div>
            <div
              class="flex flex-col gap-2 bg-gold-light rounded-2xl px-8 pt-6 py-4 pb-6 text-center"
            >
              <span class="text-5xl font-light text-blue-dark-40">
                {data.statistics.classes}
              </span>
              <span class="text-md font-medium uppercase text-blue-dark-50">Groups</span>
            </div>
            <div
              class="flex flex-col gap-2 bg-gold-light rounded-2xl px-8 pt-6 py-4 pb-6 text-center"
            >
              <span class="text-5xl font-light text-blue-dark-40">
                {data.statistics.users}
              </span>
              <span class="text-md font-medium uppercase text-blue-dark-50">Users</span>
            </div>
            {#if data.statistics.users}
              <div
                class="flex flex-col gap-2 bg-gold-light rounded-2xl px-8 pt-6 py-4 pb-6 text-center"
              >
                <span class="text-5xl font-light text-blue-dark-40">
                  {(data.statistics.enrollments / data.statistics.users).toFixed(1)}
                </span>
                <span class="text-md font-medium uppercase text-blue-dark-50"
                  >Average enrollments<br />per user</span
                >
              </div>
            {/if}
            <div
              class="flex flex-col gap-2 bg-gold-light rounded-2xl px-8 pt-6 py-4 pb-6 text-center"
            >
              <span class="text-5xl font-light text-blue-dark-40">
                {data.statistics.assistants}
              </span>
              <span class="text-md font-medium uppercase text-blue-dark-50">Assistants</span>
            </div>
            <div
              class="flex flex-col gap-2 bg-gold-light rounded-2xl px-8 pt-6 py-4 pb-6 text-center"
            >
              <span class="text-5xl font-light text-blue-dark-40">
                {data.statistics.threads}
              </span>
              <span class="text-md font-medium uppercase text-blue-dark-50">Threads</span>
            </div>
            <div
              class="flex flex-col gap-2 bg-gold-light rounded-2xl px-8 pt-6 py-4 pb-6 text-center"
            >
              <span class="text-5xl font-light text-blue-dark-40">
                {data.statistics.files}
              </span>
              <span class="text-md font-medium uppercase text-blue-dark-50">Files</span>
            </div>
          </div>
        {/if}
        <Hr />
        <Button
          class="bg-orange text-white rounded-full hover:bg-orange-dark"
          href="/admin/providers">Manage External Login Providers</Button
        >
        <Button
          class="bg-orange text-white rounded-full hover:bg-orange-dark"
          href="/admin/terms">Manage User Agreements</Button
        >
      </div>
    </div>

    <div class="sm:col-start-1 sm:col-end-2 sm:row-start-1 h-full overflow-y-auto">
      <h3 class="font-normal text-2xl border-b border-gray-200 pb-1">Groups</h3>
      <div class="flex flex-wrap flex-col">
        {#each classes as cls}
          <a
            href={`/group/${cls.id}`}
            class="border-b border-gray-200 pb-4 pt-4 transition-all duration-300 hover:bg-gray-100 hover:pl-4"
          >
            <div>
              <div class="flex flex-row gap-1">
                <h4 class="eyebrow eyebrow-dark shrink-0">
                  {cls.institution?.name || 'Unknown Institution'}
                </h4>
                <h4 class="eyebrow eyebrow-dark shrink-0">|</h4>
                <h4 class="eyebrow eyebrow-dark shrink truncate">
                  {cls.term || 'Unknown Session'}
                </h4>
              </div>
              <div class="pt-2 font-light text-lg pb-2">
                {cls.name || 'Unknown'}
              </div>
              <div class="text-gray-400 text-xs tracking-wide pb-1 uppercase">
                {dayjs.utc(cls.updated).fromNow()}
              </div>
            </div>
          </a>
        {/each}

        {#if classes.length === 0}
          <div>No groups found</div>
        {/if}
      </div>
    </div>
  </div>
</div>
