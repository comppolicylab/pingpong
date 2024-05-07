<script lang="ts">
  import PageHeader, { mainTextClass } from '$lib/components/PageHeader.svelte';
  import * as api from '$lib/api';
  import dayjs from '$lib/time';
  import { writable } from 'svelte/store';
  import { Select } from 'flowbite-svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';

  export let data;

  const classOptions = [
    { value: '0', name: 'any' },
    ...data.classes.map((cls) => ({ value: `${cls.id}`, name: cls.name }))
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

  const updateSearch = (key: string, value: string) => {
    const searchParams = $page.url.searchParams;
    searchParams.set(key, value);
    goto(`/threads?${searchParams.toString()}`);
  };

  const getValue = (el: EventTarget | null) => {
    if (!el) {
      return '';
    }
    if ((el as HTMLInputElement).value) {
      return (el as HTMLInputElement).value;
    }
    return '';
  };
</script>

<PageHeader>
  <h2 class={mainTextClass} slot="left">Threads Archive</h2>
</PageHeader>

<!-- TODO: search is not yet fully supported. -->
<div class="p-8 w-96">
  <label for="class">Class</label>
  <Select
    items={classOptions}
    on:change={(e) => updateSearch('class_id', getValue(e.target))}
    value={currentClass}
    name="class"
  />
</div>

<h3>Threads</h3>
<div class="flex flex-wrap gap-4 p-8 flex-col">
  {#each data.threadArchive.threads as thread}
    <a href={`/class/${thread.class_id}/thread/${thread.id}`}>
      <div>
        <h4>{classNamesLookup[thread.class_id]?.name || 'Unknown'}</h4>
        <div>
          {thread.name}
        </div>
        <div>
          {dayjs.utc(thread.updated).fromNow()}
        </div>
        <div>
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
