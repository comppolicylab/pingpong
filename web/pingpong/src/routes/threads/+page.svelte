<script lang="ts">
  import PageHeader from '$lib/components/PageHeader.svelte';
  import * as api from '$lib/api';
  import dayjs from '$lib/time';
  import { Select, Button } from 'flowbite-svelte';
  import { page } from '$app/stores';
  import { getValue, updateSearch } from '$lib/urlstate';
  import { loading } from '$lib/stores/general';

  export let data;

  const classOptions = [
    { value: '0', name: 'All' },
    ...data.classes
      .map((cls) => ({ value: `${cls.id}`, name: cls.name }))
      .sort((a, b) => a.name.localeCompare(b.name))
  ];
  $: currentClass = $page.url.searchParams.get('class_id') || '0';
  $: threads = data.threadArchive.threads || [];
  $: hasMore = !data.threadArchive.lastPage;
  $: error = data.threadArchive.error;

  const classNamesLookup = data.classes.reduce(
    (acc, cls) => {
      acc[cls.id] = cls;
      return acc;
    },
    {} as Record<number, api.Class>
  );

  const fetchNextPage = async () => {
    if (!hasMore) {
      return;
    }

    if (error) {
      return;
    }

    $loading = true;

    const lastTs = threads.length ? threads[threads.length - 1].updated : undefined;
    const currentClassId = parseInt(currentClass, 10) || undefined;
    const more = await api.getAllThreads(fetch, { before: lastTs, class_id: currentClassId });
    $loading = false;
    if (more.error) {
      error = more.error;
    } else {
      threads = [...threads, ...more.threads];
      hasMore = !more.lastPage;
      error = null;
    }
  };
</script>

<div class="h-full w-full flex flex-col">
  <PageHeader>
    <h2 class="text-3xl text-color-blue-dark-50 font-serif font-bold px-4 py-3" slot="left">
      Threads Archive
    </h2>
  </PageHeader>

  <!-- TODO: search is not yet fully supported. -->

  <div class="grid gap-12 p-12 sm:grid-cols-[2fr_1fr] min-h-0 grow shrink">
    <div class="sm:col-start-2 sm:col-end-3">
      <label for="class" class="text-xs uppercase tracking-wide block pb-2 pt-8"
        >Filter by <b>Group</b></label
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
        {#each threads as thread}
          {@const allUsers = thread.user_names || []}
          {@const allUsersLen = allUsers.length}
          {@const otherUsers = thread.user_names?.filter((user_name) => user_name != 'Me') || []}
          {@const otherUsersLen = otherUsers.length}
          <a
            href={`/group/${thread.class_id}/thread/${thread.id}`}
            class="border-b border-gray-200 pb-4 pt-4 transition-all duration-300 hover:bg-gray-100 hover:pl-4"
          >
            <div>
              <div class="flex flex-row gap-1">
                <h4 class="eyebrow eyebrow-dark shrink-0">
                  {classNamesLookup[thread.class_id]?.name || 'Unknown Group'}
                </h4>
                <h4 class="eyebrow eyebrow-dark shrink-0">|</h4>
                <h4 class="eyebrow eyebrow-dark shrink truncate">
                  {Object.values(thread.assistant_names || { 1: 'Unknown Assistant' }).join(', ')}
                </h4>
              </div>
              <div class="pt-2 font-light text-lg pb-2">
                {thread.name}
              </div>
              <div class="text-gray-400 text-xs tracking-wide pb-1 uppercase">
                {dayjs.utc(thread.updated).fromNow()}
              </div>
              <div class="text-gray-400 text-xs uppercase tracking-wide">
                {thread.private
                  ? allUsersLen != otherUsersLen
                    ? `me${
                        otherUsersLen > 0
                          ? otherUsersLen == 1
                            ? ' & Anonymous User'
                            : ' & ' + otherUsersLen + ' Anonymous Users'
                          : ''
                      }`
                    : 'Anonymous User'
                  : allUsersLen != otherUsersLen
                    ? `me${
                        otherUsersLen > 0
                          ? otherUsers.map((user_name) => user_name || 'Anonymous User').join(', ')
                          : ''
                      }`
                    : allUsers.map((user_name) => user_name || 'Anonymous User').join(', ')}
              </div>
            </div>
          </a>
        {/each}

        {#if data.threadArchive.threads.length === 0}
          <div class="text-center py-8 text-gray-400 text-sm tracking-wide uppercase">
            No threads found
          </div>
        {/if}

        {#if error}
          <div class="text-center py-8 text-red-400 text-sm tracking-wide uppercase">
            Error: {error}
          </div>
        {/if}

        {#if hasMore}
          <div class="text-center py-8 tracking-wide uppercase">
            <Button
              class="text-blue-dark-40 uppercase tracking-wide hover:bg-gray-100"
              on:click={fetchNextPage}>Load more ...</Button
            >
          </div>
        {/if}
      </div>
    </div>
  </div>
</div>
