<script lang="ts">
  // Import necessary components from Flowbite-Svelte
  import { Input, Button } from 'flowbite-svelte';
  import {enhance} from '$app/forms';

  export let data;

  const threadUrl = (id: string) => `/class/${data.class.id}/thread/${id}`;

  const formUrl = data.currentThread ?
    `/class/${data.class.id}/thread/${data.currentThread}?/newMessage` :
    `/class/${data.class.id}/thread?/newThread`;

  let thread = [];
  let threads = [];

  $: {
    threads = data?.class?.threads || [];
    threads.sort((a, b) => {
      return new Date(b.created).getTime() - new Date(a.created).getTime();
    });

    thread = data?.thread?.data || [];
  }

  const scrollToBottom = (node) => {
    const scroll = () => node.scroll({
      top: node.scrollHeight,
      behavior: 'smooth'
    });
    scroll();
    return {update: scroll};
  };
</script>

<div class="flex h-screen">
    <div class="basis-64 grow-0 shrink-0 overflow-y-auto p-4 bg-sky-800">
        <!-- List of chat threads -->
        <ul>
            {#each threads as thread}
                <li
                    class="p-2 hover:bg-sky-700 cursor-pointer rounded"
                    class:bg-sky-700={thread.id === data.currentThread}
                >
                  <a href="{threadUrl(thread.id)}" class="block">
                    <h3 class="font-semibold text-white">{thread.name}</h3>
                    <p class="text-sm text-stone-200">{thread.name}</p>
                  </a>
                </li>
            {/each}
        </ul>
    </div>
    <div class="flex flex-col flex-grow">
        <div class="flex-grow overflow-y-auto p-4 bg-white" use:scrollToBottom={thread}>
            <!-- Selected conversation -->
            <slot></slot>
        </div>
        <form action={formUrl} method="POST" use:enhance>
        <div class="flex items-center border-t border-gray-300 p-4">
            <Input placeholder="Type a message..." name="message" id="message" class="w-full mr-2" />
            <Button type="submit" color="dark">Send</Button>
          </div>
        </form>
    </div>
</div>
