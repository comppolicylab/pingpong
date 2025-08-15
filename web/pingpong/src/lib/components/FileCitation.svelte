<script lang="ts">
  import { Modal } from 'flowbite-svelte';
  import { FileSolid } from 'flowbite-svelte-icons';
  import Markdown from './Markdown.svelte';

  export let name: string;
  export let quote: string;
  let isOpen = false;
</script>

<Modal bind:open={isOpen} title={`Text used from "${name}"`} autoclose outsideclose dismissable>
  <Markdown content={quote} syntax={true}/>
</Modal>

<button
  class="hover:shadow relative rounded-lg items-center border-[1px] border-solid border-gray-300 bg-white flex px-2"
  on:click={() => (isOpen = true)}
  disabled={!quote}
>
  <div>
    <FileSolid class="w-6 h-6 text-green-500" />
  </div>
  <div class="flex flex-col p-2 items-start">
    <div class="text-xs text-gray-500 font-bold">{name}</div>
    <div class="text-xs text-gray-500">Citation</div>
  </div>
</button>
