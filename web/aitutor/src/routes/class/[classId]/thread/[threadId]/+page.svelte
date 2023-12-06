<script lang="ts">
  import {Avatar} from "flowbite-svelte";
  import SvelteMarkdown from "svelte-markdown";

  export let data;

  let thread = [];

  $: {
    thread = (data?.thread?.data || []);
    thread.sort((a, b) => a.created_at - b.created_at);
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
