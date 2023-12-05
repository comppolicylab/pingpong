<script lang="ts">
  // Import necessary components from Flowbite-Svelte
  import { Input, Button } from 'flowbite-svelte';

  export let data;

  const threadUrl = (id: string) => `/class/${data.class.id}/thread/${id}`;

  const formUrl = data.currentThread ?
    `/class/${data.class.id}/thread/${data.currentThread}?/newMessage` :
    `/class/${data.class.id}/thread?/newThread`;
</script>

<div class="flex h-screen">
    <div class="w-1/5 overflow-y-auto p-4 bg-sky-800">
        <!-- List of chat threads -->
        <ul>
            {#each data.class.threads as thread}
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
    <div class="flex-grow flex flex-col">
        <div class="flex-grow overflow-y-auto p-4 bg-white">
            <!-- Selected conversation -->
            <slot></slot>
        </div>
        <form action={formUrl} method="POST">
        <div class="flex items-center border-t border-gray-300 p-4">
            <Input placeholder="Type a message..." name="message" id="message" class="w-full mr-2" />
            <Button type="submit" color="dark">Send</Button>
          </div>
        </form>
    </div>
</div>
