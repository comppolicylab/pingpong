<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import * as api from '$lib/api';
  import { parseAddresses, type EmailTuple } from '$lib/email';
  import { Select, Helper, Button, Label, Textarea, Hr, Checkbox, Table, TableHead, TableHeadCell, TableBody, TableBodyRow, TableBodyCell, Input } from 'flowbite-svelte';
  import { writable } from 'svelte/store';
  import { sadToast } from '$lib/toast';
  import {
    AngleDownOutline,
    LockSolid,
    QuestionCircleOutline,
    ExclamationCircleOutline,
    CheckOutline
  } from 'flowbite-svelte-icons';
  import PermissionsTable from './PermissionsTable.svelte';

  export let role: api.Role;
  export let className: string = 'your group';
  export let isPrivate: boolean = false;
  export let permissions: { name: string; member: boolean; moderator: boolean }[] = [];
  let emailString: string = '';
  let emailList: EmailTuple[] = [];
  $: verifiedEmails = emailList.filter((e) => e[2]);
  $: unverifiedEmails = emailList.filter((e) => !e[2]);
  let selectedRole: api.Role | undefined = role;
  let silentAdd = false;
  let showEmailForm = true;
  let showNameForm = false;

  let permissionsModalOpen = false;

  const dispatch = createEventDispatcher();

  const loading = writable(false);
  const submitEmailForm = (evt: SubmitEvent) => {
    evt.preventDefault();
    $loading = true;

    const form = evt.target as HTMLFormElement;
    const formData = new FormData(form);
    const d = Object.fromEntries(formData.entries());

    const emails = (d.emails as string) || '';
    if (!emails) {
      $loading = false;
      sadToast('Emails are required');
      return;
    }
    emailString = emails;
    emailList = parseAddresses(emails);

    selectedRole = d.role as api.Role | undefined;
    if (!selectedRole) {
      $loading = false;
      sadToast('Role is required');
      return;
    }

    silentAdd = d.notify !== 'on';

    // const request: api.CreateClassUsersRequest = {
    //   roles: emailList.map((e) => ({
    //     email: e,
    //     roles: {
    //       admin: role === 'admin',
    //       teacher: role === 'teacher',
    //       student: role === 'student'
    //     }
    //   })),
    //   silent: silent
    // };

    // dispatch('submit', request);
    $loading = false;
    showEmailForm = false;
    showNameForm = true;
  };

  const roles = api.ROLES.filter((role) => role !== 'admin').map((role) => ({
    value: role,
    name: api.ROLE_LABELS[role]
  }));
</script>

{#if showEmailForm}
  <form on:submit={submitEmailForm}>
    <Label defaultClass="text-md font-normal rtl:text-right font-medium block" for="emails"
      >Emails</Label
    >
    <Helper helperClass="text-sm font-normal text-gray-500 dark:text-gray-300"
      >Enter email addresses separated by commas or newlines.</Helper
    >
    <Textarea class="mt-2 mb-4" id="emails" name="emails" rows="4" value={emailString} />

    <div class="flex items-center justify-between">
      <Label defaultClass="text-md font-normal rtl:text-right font-medium block" for="role"
        >Role</Label
      >
      <Button
        class="flex flex-row items-center gap-1 text-sm font-normal text-gray-500 hover:underline p-0"
        on:click={() => (permissionsModalOpen = !permissionsModalOpen)}
        on:touchstart={() => (permissionsModalOpen = !permissionsModalOpen)}
      >
        {permissionsModalOpen ? 'Hide' : 'Show'} permissions
        {#if permissionsModalOpen}
          <AngleDownOutline class="w-4 h-4" />
        {:else}
          <QuestionCircleOutline class="w-4 h-4" />
        {/if}
      </Button>
    </div>
    <div
      class="overflow-hidden transition-all duration-300 ease-in-out"
      class:max-h-0={!permissionsModalOpen}
      class:max-h-[500px]={permissionsModalOpen}
      class:opacity-0={!permissionsModalOpen}
      class:opacity-100={permissionsModalOpen}
    >
      <div class="rounded-lg overflow-hidden shadow-md my-4 relative">
        {#if isPrivate}
          <div
            class="flex items-center text-sm text-white bg-gradient-to-r from-gray-800 to-gray-600 border-gradient-to-r from-gray-800 to-gray-600 p-4"
          >
            <LockSolid class="w-8 h-8 mr-3" />
            <span>
              Threads and assistants are private in your group, so Moderators have limited
              permissions compared to a non-private group.
            </span>
          </div>
        {/if}
        <div
          class="bg-white border rounded-lg border-gray-300 overflow-hidden"
          class:rounded-lg={!isPrivate}
          class:rounded-b-lg={isPrivate}
        >
          <PermissionsTable {permissions} />
        </div>
      </div>
    </div>
    <Helper helperClass="text-sm font-normal text-gray-500 dark:text-gray-300">
      <div>Choose a user role to grant permissions to these users to view the group.</div>
    </Helper>
    <Select
      id="role"
      name="role"
      class="py-1.5 mt-2 mb-4"
      placeholder="Select a user role..."
      value={selectedRole}
      items={roles}
    />
    <Helper helperClass="text-md font-normal rtl:text-right font-medium block">Notify people</Helper
    >
    <Checkbox checked id="notify" name="notify" class="mt-1 text-sm font-normal"
      >Let users know they have access to {className} on PingPong</Checkbox
    >
    <Hr />

    <div class="flex flex-row justify-end gap-2">
      <Button
        type="button"
        pill
        class="bg-blue-light-50 border rounded-full border-blue-dark-40 text-blue-dark-50 hover:bg-blue-light-40"
        disabled={$loading}
        on:click={() => dispatch('cancel')}
        on:touchstart={() => dispatch('cancel')}>Cancel</Button
      >
      <Button
        type="submit"
        pill
        class="bg-orange border border-orange-dark text-white hover:bg-orange-dark"
        disabled={$loading}>Next</Button
      >
    </div>
  </form>
{:else if showNameForm}
  <form on:submit={submitEmailForm}>
{#if unverifiedEmails.length > 0}
<div
class="flex items-center text-sm text-white bg-gradient-to-r from-red-900 to-red-700 border border-gradient-to-r from-red-800 to-red-600 px-4 py-3 rounded-lg"
>
<ExclamationCircleOutline class="w-8 h-8 mr-3" />
<div class="flex flex-col">
  <span class="font-bold">Unverified Users</span><span
    >We were unable to confirm the emails you entered for the following users. Please confirm
    before continuing.</span
  >
</div>
</div>

<Table class="min-w-full text-sm text-left text-gray-500">
  <TableHead>
      <TableHeadCell class="px-6 py-4 font-medium text-gray-900">Name</TableHeadCell>
      <TableHeadCell class="px-6 py-4 font-medium text-gray-900">Email</TableHeadCell>
  </TableHead>
  <TableBody>
    {#each emailList as tuple, index}
      <TableBodyRow class="bg-white border-b">
        <!-- Name Input -->
        <TableBodyCell class="px-3 py-2">
          <Input
            type="text"
            placeholder="Name"
            class="w-full px-2 py-1 border rounded"
            value={tuple[0] || ''}
          />
        </TableBodyCell>

        <!-- Email Input -->
        <TableBodyCell class="px-6 py-4">
          <Input
            type="email"
            placeholder="Email"
            class="w-full px-2 py-1 border rounded"
            value={tuple[1]}
          />
        </TableBodyCell>
      </TableBodyRow>
    {/each}
  </TableBody>
</Table>
<Hr />
{/if}
    <div
      class="flex items-center text-sm text-white bg-gradient-to-r from-green-800 to-green-600 border border-green-400 px-4 py-1 rounded-lg"
    >
      <CheckOutline class="w-8 h-8 mr-3 text-green-400" />
      <span>The following users are ready to be added to the group.</span>
    </div>

    <Hr />

    <div class="flex flex-row justify-end gap-2">
      <Button
        type="button"
        pill
        class="bg-blue-light-50 border rounded-full border-blue-dark-40 text-blue-dark-50 hover:bg-blue-light-40"
        disabled={$loading}
        on:click={() => dispatch('cancel')}
        on:touchstart={() => dispatch('cancel')}>Cancel</Button
      >
      <div class="flex flex-row justify-end gap-2">
        <Button
          type="button"
          pill
          class="bg-blue-light-50 border rounded-full border-blue-dark-40 text-blue-dark-50 hover:bg-blue-light-40"
          disabled={$loading}
          on:click={() => {
            showNameForm = false;
            showEmailForm = true;
          }}
          on:touchstart={() => {
            showNameForm = false;
            showEmailForm = true;
          }}>Back</Button
        >
        <Button
          type="submit"
          pill
          class="bg-orange border border-orange-dark text-white hover:bg-orange-dark"
          disabled={$loading}>Submit</Button
        >
      </div>
    </div>
  </form>
{/if}
