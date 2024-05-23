<script lang="ts">
  import PageHeader from '$lib/components/PageHeader.svelte';
  import * as api from '$lib/api';
  import dayjs from '$lib/time';
  import { writable } from 'svelte/store';
  import { Select } from 'flowbite-svelte';
  import { page } from '$app/stores';
  import { getValue, updateSearch } from '$lib/urlstate';

  export let data;

  const classOptions = [
    { value: '0', name: 'Any' },
    ...data.classes.map((cls) => ({ value: `${cls.id}`, name: cls.name })).sort((a, b) => a.name.localeCompare(b.name)),
  ];
  let currentClass = $page.url.searchParams.get('class_id') || '0';
  const threads = writable(data.threadArchive.threads || []);
  const hasMore = writable(!data.threadArchive.lastPage);
  const error = writable(data.threadArchive.error);

  const classNamesLookup = data.classes.reduce(
    (acc, cls) => {
      acc[cls.id] = cls;
      return acc;
    },
    {} as Record<number, api.Class>
  );

  const fetchNextPage = async () => {
    if (!$hasMore) {
      return;
    }

    if ($error) {
      return;
    }
    const lastTs = $threads.length ? $threads[$threads.length - 1].updated : undefined;
    const more = await api.getAllThreads(fetch, { before: lastTs });
    if (more.error) {
      $error = more.error;
    } else {
      $threads = [...$threads, ...more.threads];
      $hasMore = !more.lastPage;
      $error = null;
    }
  };
</script>

<div class="h-full w-full flex flex-col">
  <PageHeader>
    <h2 class="text-3xl text-color-blue-dark-50 font-serif font-bold px-4 pb-3 pt-6" slot="left">
      Threads Archive
    </h2>
  </PageHeader>

  <!-- TODO: search is not yet fully supported. -->

  <div class="grid gap-12 p-12 sm:grid-cols-[2fr_1fr] min-h-0 grow shrink">
    <div class="sm:col-start-2 sm:col-end-3">
      <label for="class" class="text-xs uppercase tracking-wide block pb-2 pt-8"
        >Filter by <b>Class</b></label
      >
      <Select
        items={classOptions}
        on:change={(e) => updateSearch('class_id', getValue(e.target))}
        value={currentClass}
        name="class"
      />
    </div>

    <div class="sm:col-start-1 sm:col-end-2 sm:row-start-1 h-full overflow-y-auto">
      <h3 class="font-normal text-2xl border-b border-gray-200 pb-1">Threads</h3>
      <div class="flex flex-wrap flex-col">
        {#each data.threadArchive.threads as thread}
          <a
            href={`/class/${thread.class_id}/thread/${thread.id}`}
            class="border-b border-gray-200 pb-4 pt-4 transition-all duration-300 hover:bg-gray-100 hover:pl-4"
          >
            <div>
              <h4 class="eyebrow eyebrow-dark">
                {classNamesLookup[thread.class_id]?.name || 'Unknown'}
              </h4>
              <div class="pt-2 font-light text-lg pb-2">
                {thread.name}
              </div>
              <div class="text-gray-400 text-xs tracking-wide pb-1 uppercase">
                {dayjs.utc(thread.updated).fromNow()}
              </div>
              <div class="text-gray-400 text-xs uppercase tracking-wide">
                {thread.users.map((user) => user.email).join(', ')}
              </div>
            </div>
          </a>
        {/each}

        {#if data.threadArchive.threads.length === 0}
          <div>No threads found</div>
        {/if}

        {#if $error}
          <div>Error: {$error}</div>
        {/if}

        {#if $hasMore}
          <button on:click={fetchNextPage}>Load more</button>
        {/if}
      </div>
    </div>
  </div>
</div>
