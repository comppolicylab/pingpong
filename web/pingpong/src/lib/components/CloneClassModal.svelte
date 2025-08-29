<script lang="ts">
  import {
    Accordion,
    AccordionItem,
    Button,
    Checkbox,
    Input,
    Label,
    Radio,
    Select
  } from 'flowbite-svelte';
  import { createEventDispatcher } from 'svelte';
  import { FileCopyOutline } from 'flowbite-svelte-icons';
  import AzureLogo from './AzureLogo.svelte';
  import OpenAiLogo from './OpenAILogo.svelte';
  import type { CopyClassRequestInfo } from '$lib/api';

  export let groupName: string;
  export let groupSession: string;
  export let makePrivate = false;
  export let anyCanPublishThread = false;
  export let anyCanShareAssistant = false;
  export let assistantPermissions: string = 'create:0,publish:0,upload:0';
  export let aiProvider = '';

  let disableAnyCanShareAssistants = assistantPermissions.includes('publish:0');
  $: {
    disableAnyCanShareAssistants = assistantPermissions.includes('publish:0');
    if (disableAnyCanShareAssistants) {
      anyCanShareAssistant = false;
    }
  }

  let assistantCopy: 'moderators' | 'all' = 'moderators';
  let userCopy: 'moderators' | 'all' = 'moderators';

  let copyClassInfo: CopyClassRequestInfo;
  $: copyClassInfo = {
    groupName,
    groupSession,
    makePrivate,
    anyCanPublishThread,
    anyCanShareAssistant,
    assistantPermissions,
    assistantCopy,
    userCopy
  };

  const dispatch = createEventDispatcher();

  const asstPermOptions = [
    { value: 'create:0,publish:0,upload:0', name: 'Do not allow members to create' },
    { value: 'create:1,publish:0,upload:1', name: 'Members can create but not publish' },
    { value: 'create:1,publish:1,upload:1', name: 'Members can create and publish' }
  ];
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
        <div class="grid md:grid-cols-2 gap-x-6 gap-y-6 my-3">
          <div>
            <Label for="name" class="mb-1">Name</Label>
            <Input id="name" name="name" bind:value={groupName} />
          </div>
          <div>
            <Label for="term" class="mb-1">Session</Label>
            <Input id="term" name="term" bind:value={groupSession} />
          </div>
          <Checkbox id="make_private" name="make_private" bind:checked={makePrivate}>
            Make threads and assistants private
          </Checkbox>

          <Checkbox
            id="any_can_publish_thread"
            name="any_can_publish_thread"
            bind:checked={anyCanPublishThread}>Allow members to publish threads</Checkbox
          >
          <div class="content-center text-sm font-medium text-gray-900">
            Assistant Permissions for Members
          </div>
          <Select
            items={asstPermOptions}
            bind:value={assistantPermissions}
            name="asst_perm"
            class="truncate"
          />
          <Checkbox
            id="any_can_share_assistant"
            name="any_can_share_assistant"
            disabled={disableAnyCanShareAssistants}
            class={'col-span-2 ' +
              (disableAnyCanShareAssistants ? 'text-gray-400' : '!text-gray-900 !opacity-100')}
            bind:checked={anyCanShareAssistant}
            >Allow members to create public links for assistants</Checkbox
          >
        </div>
      </AccordionItem>
      <AccordionItem paddingFlush="py-2">
        <span slot="header" class="w-full mr-3"
          ><div class="flex-row flex justify-between items-center space-x-2 w-full">
            <div>AI Provider</div>
            <div class="font-light text-sm flex flex-row items-center gap-1">
              {#if aiProvider === 'azure'}
                <AzureLogo size="4" />
                <div>Azure</div>
              {:else if aiProvider === 'openai'}
                <OpenAiLogo size="4" />
                <div>OpenAI</div>
              {:else}
                <div>Same as original group</div>
              {/if}
            </div>
          </div></span
        >
        <p class="mb-2 text-gray-500 text-sm font-light">
          Your new group will share the same files with the original group, which requires the same
          billing details, including your AI Provider.
        </p>
      </AccordionItem>
      <AccordionItem paddingFlush="py-2">
        <span slot="header" class="w-full mr-3"
          ><div class="flex-row flex justify-between items-center space-x-2 w-full">
            <div>Assistants</div>
            <div class="font-light text-sm">
              {#if assistantCopy === 'moderators'}
                Copy only published Moderator Assistants
              {:else if assistantCopy === 'all'}
                Copy all published Assistants
              {:else}
                No assistants will be copied
              {/if}
            </div>
          </div></span
        >
        <p class="mb-2 text-gray-500 text-sm font-light">
          Choose which assistants to copy over to the new group. You can also create new assistants
          in the new group. If you choose to copy assistants created by members, they will be added
          as users in the new group.
        </p>
        <Radio name="moderatorOnlyAssistants" value="moderators" bind:group={assistantCopy}
          >Copy only&nbsp;<span class="italic">published</span>&nbsp;Moderator Assistants</Radio
        >
        <Radio
          name="allAssistants"
          value="all"
          bind:group={assistantCopy}
          on:click={() => {
            userCopy = 'all';
          }}
          >Copy all&nbsp;<span class="italic">published</span>&nbsp;Assistants, including those
          created by members</Radio
        >
      </AccordionItem>
      <AccordionItem paddingFlush="py-2">
        <span slot="header" class="w-full mr-3"
          ><div class="flex-row flex justify-between items-center space-x-2 w-full">
            <div>Users</div>
            <div class="font-light text-sm">
              {#if userCopy === 'moderators'}
                Copy only Moderators
              {:else if userCopy === 'all'}
                Copy all users
              {:else}
                No users will be copied
              {/if}
            </div>
          </div></span
        >
        <p class="mb-2 text-gray-500 text-sm font-light">
          Choose which users to copy over to the new group. You can also add new users in the new
          group. If you choose to copy assistants created by members, all members will be added as
          users in the new group.
        </p>
        <Radio
          name="moderatorOnlyUsers"
          value="moderators"
          bind:group={userCopy}
          disabled={assistantCopy === 'all'}>Copy only Moderators</Radio
        >
        {#if assistantCopy === 'all'}
          <p class="text-sm text-gray-500 mb-2">
            If you copy all assistants, all users will be copied as well.
          </p>
        {/if}
        <Radio name="allUsers" value="all" bind:group={userCopy}>Copy all users</Radio>
      </AccordionItem>
    </Accordion>
  </div>
  <div class="flex justify-center gap-4">
    <Button pill color="alternative" on:click={() => dispatch('cancel')}>Cancel</Button>
    <Button pill outline color="blue" on:click={() => dispatch('confirm', copyClassInfo)}
      >Clone Group</Button
    >
  </div>
</div>
