<script lang="ts">
  import { Accordion, AccordionItem, Button, Checkbox, Input, Label } from 'flowbite-svelte';
  import { createEventDispatcher } from 'svelte';
  import { ExclamationCircleOutline, FileCopyOutline } from 'flowbite-svelte-icons';

  export let warningTitle: string;
  export let warningDescription: string;
  export let warningMessage: string;
  export let cancelButtonText: string;
  export let confirmText: string;

  export let confirmButtonText: string;

  const dispatch = createEventDispatcher();
  let confirmInput = '';
</script>

<div class="text-center px-2">
  <FileCopyOutline class="mx-auto mb-4 text-blue-dark-40 w-12 h-12" />
  <h3 class="mb-1 text-xl text-gray-900 dark:text-white font-bold">Clone Group</h3>
  <p class="mb-5 text-gray-700 dark:text-gray-300 w-2/3 mx-auto">
    Configure the new group and choose what content to copy over from the original group.
  </p>
  <div class="mb-4 px-4">
    <Accordion class="w-full text-left" flush multiple>
      <AccordionItem paddingFlush="py-2" open>
        <span slot="header" class="w-full mr-3"
          ><div class="flex-row flex justify-between items-center space-x-2 w-full">
            <div>Group Details</div>
          </div></span
        >
        <div class="grid md:grid-cols-2 gap-x-6 gap-y-4">
          <div>
            <Label for="name" class="mb-1">Name</Label>
            <Input id="name" name="name" />
          </div>
          <div>
            <Label for="term" class="mb-1">Session</Label>
            <Input id="term" name="term" />
          </div>
          <Checkbox id="make_private" name="make_private">
            Make threads and assistants private
          </Checkbox>
        </div>
      </AccordionItem>
      <AccordionItem paddingFlush="py-2" open>
        <span slot="header" class="w-full mr-3"
          ><div class="flex-row flex justify-between items-center space-x-2 w-full">
            <div>Billing</div>
            <div class="font-light">Same as original group</div>
          </div></span
        >
        <p class="mb-2 text-gray-500 dark:text-gray-400">
          Lorem ipsum dolor sit amet, consectetur adipisicing elit. Illo ab necessitatibus sint
          explicabo ...
        </p>
        <p class="text-gray-500 dark:text-gray-400">
          Check out this guide to learn how to <a
            href="/"
            target="_blank"
            rel="noreferrer"
            class="text-blue-600 hover:underline dark:text-blue-500">get started</a
          >
          and start developing websites even faster with components on top of Tailwind CSS.
        </p>
      </AccordionItem>
      <AccordionItem paddingFlush="py-2" open>
        <span slot="header" class="w-full mr-3"
          ><div class="flex-row flex justify-between items-center space-x-2 w-full">
            <div>Billing</div>
            <div class="font-light">Same as original group</div>
          </div></span
        >
        <p class="mb-2 text-gray-500 dark:text-gray-400">
          Lorem ipsum dolor sit amet, consectetur adipisicing elit. Illo ab necessitatibus sint
          explicabo ...
        </p>
        <p class="text-gray-500 dark:text-gray-400">
          Check out this guide to learn how to <a
            href="/"
            target="_blank"
            rel="noreferrer"
            class="text-blue-600 hover:underline dark:text-blue-500">get started</a
          >
          and start developing websites even faster with components on top of Tailwind CSS.
        </p>
      </AccordionItem>
    </Accordion>
  </div>
  <div class="flex justify-center gap-4">
    <Button pill color="alternative" on:click={() => dispatch('cancel')}>{cancelButtonText}</Button>
    <Button
      pill
      outline
      color="blue"
      disabled={confirmInput.toLowerCase() !== confirmText}
      on:click={() => dispatch('confirm')}
    >
      {confirmButtonText}
    </Button>
  </div>
</div>
