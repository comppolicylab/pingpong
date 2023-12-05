<script lang="ts">
  import SvelteMarkdown from "svelte-markdown";

  export let data;

  const thread = (data?.thread?.data || []).reverse();

  console.log(thread)
</script>

<div class="w-full divide-y">
  {#each thread as message}
    <div>
    {#each message.content as content}
      <div><SvelteMarkdown source="{content.text.value}" /></div>
    {/each}
    </div>
  {/each}
</div>
