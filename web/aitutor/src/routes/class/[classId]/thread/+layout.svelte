<script lang="ts">
  import * as api from '$lib/api';
  import { Input, Button } from 'flowbite-svelte';
  import {enhance} from '$app/forms';
  import { goto, invalidateAll } from '$app/navigation';

  export let data;

  let threadUrl = (id: string) => "";
  let formUrl = "";
  let thread = [];
  let threads = [];
  let currentThread = null;

  $: {
    currentThread = data.currentThread;
    threadUrl = (id: string) => `/class/${data.class.id}/thread/${id}`;

    formUrl = data.currentThread ?
        `/class/${data.class.id}/thread/${currentThread}?/newMessage` :
        `/class/${data.class.id}/thread?/newThread`;

    threads = data?.class?.threads || [];

    threads.sort((a, b) => {
      return new Date(b.created).getTime() - new Date(a.created).getTime();
    });

    thread = data?.thread?.data || [];
  }

  /**
   * Scroll to the bottom of the thread.
   */
  const scrollToBottom = (node) => {
    const scroll = () => node.scroll({
      top: node.scrollHeight,
      behavior: 'smooth'
    });
    scroll();
    return {update: scroll};
  };

  /**
   * Fetch the response from the openai thread.
   */
  const pollForResponse = () => {
    return async ({ result, update}) => {
      update();
      await invalidateAll();
      if (!currentThread) {
        goto(`/class/${data.class.id}/thread/${result.data.thread.id}`);
      } else {
        await api.getLastThreadRun(fetch, data.class.id, result.data.thread.id);
      }
    };
  };
</script>

<div class="flex h-screen">
    <div class="basis-64 grow-0 shrink-0 overflow-y-auto p-4 bg-sky-800">
        <!-- List of chat threads -->
        <ul>
            <li>
              <a href="/class/{data.class.id}/thread" class="block p-2 hover:bg-sky-700 cursor-pointer rounded">
                <span>New</span>
              </a>
            </li>
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
        <form action={formUrl} method="POST" use:enhance={pollForResponse}>
        <div class="flex items-center border-t border-gray-300 p-4">
            <Input placeholder="Type a message..." name="message" id="message" class="w-full mr-2" autocomplete="off" />
            <Button type="submit" color="dark">Send</Button>
          </div>
        </form>
    </div>
</div>
