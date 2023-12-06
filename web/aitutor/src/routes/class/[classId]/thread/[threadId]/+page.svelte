<script lang="ts">
  import * as api from '$lib/api';
  import {browser} from '$app/environment';
  import {invalidateAll} from '$app/navigation';
  import {Avatar} from "flowbite-svelte";
  import SvelteMarkdown from "svelte-markdown";

  export let data;

  let thread = [];

  let lastLoadedRun = "";

  $: {
    thread = (data?.messages?.data || []);
    thread.sort((a, b) => a.created_at - b.created_at);
    if (!lastLoadedRun) {
      lastLoadedRun = data?.run?.id;
    }

    if (browser && data.currentThread && !api.finished(data?.run)) {
      api.getLastThreadRun(fetch, data.class.id, data.currentThread).then((result) => {
        if (result.run.id !== lastLoadedRun) {
          lastLoadedRun = result.run.id;
          invalidateAll();
        }
      });
    }
  }
</script>

<div class="w-full px-2">
  {#each thread as message}
    <div class="py-4 px-6 flex gap-x-3">
      <div><Avatar size="xs" /></div>
      <div>
        <div class="font-bold text-gray-400">{message.role}</div>
        {#each message.content as content}
          <div class="leading-7"><SvelteMarkdown source="{content.text.value}" /></div>
        {/each}
      </div>
    </div>
  {/each}
</div>
