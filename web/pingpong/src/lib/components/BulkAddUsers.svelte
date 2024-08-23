<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import * as api from '$lib/api';
  import { Select, Helper, Button, Label, Textarea, Hr, Checkbox } from 'flowbite-svelte';
  import { writable } from 'svelte/store';
  import { sadToast } from '$lib/toast';
  import { AngleDownOutline, LockSolid, QuestionCircleOutline } from 'flowbite-svelte-icons';
  import PermissionsTable from './PermissionsTable.svelte';

  export let role: api.Role;
  export let className: string = 'your group';
  export let isPrivate: boolean = false;
  export let permissions: { name: string; member: boolean; moderator: boolean }[] = [];

  let permissionsModalOpen = false;

  const dispatch = createEventDispatcher();

  const loading = writable(false);
  const submitForm = (evt: SubmitEvent) => {
    evt.preventDefault();
    $loading = true;

    const form = evt.target as HTMLFormElement;
    const formData = new FormData(form);
    const d = Object.fromEntries(formData.entries());

    const emails = (d.emails as string) || '';
    // Split emails by newlines or commas.
    // TODO: Add email validation.
    const emailList = emails
      .split(/[\n,]+/)
      .map((e) => e.trim())
      .filter((e) => e.length > 0);

    if (emailList.length === 0) {
      $loading = false;
      sadToast('Emails are required');
    }

    const role = d.role as api.Role | undefined;
    if (!role) {
      $loading = false;
      sadToast('Role is required');
    }

    const silent = d.notify !== 'on';

    const request: api.CreateClassUsersRequest = {
      roles: emailList.map((e) => ({
        email: e,
        roles: {
          admin: role === 'admin',
          teacher: role === 'teacher',
          student: role === 'student'
        }
      })),
      silent: silent
    };

    dispatch('submit', request);
  };

  const roles = api.ROLES.filter((role) => role !== 'admin').map((role) => ({
    value: role,
    name: api.ROLE_LABELS[role]
  }));
</script>

<form on:submit={submitForm}>
  <Label defaultClass="text-md font-normal rtl:text-right font-medium block" for="emails"
    >Emails</Label
  >
  <Helper helperClass="text-sm font-normal text-gray-500 dark:text-gray-300"
    >Enter email addresses separated by commas or newlines.</Helper
  >
  <Textarea class="mt-2 mb-4" id="emails" name="emails" rows="4" />

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
            Threads and assistants are private in your group, so Moderators have limited permissions
            compared to a non-private group.
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
    value={role}
    items={roles}
  />
  <Helper helperClass="text-md font-normal rtl:text-right font-medium block">Notify people</Helper>
  <Checkbox checked id="notify" name="notify" class="mt-1 text-sm font-normal"
    >Let users know they have access to {className} on PingPong</Checkbox
  >
  <Hr />
  <div>
    <Button
      type="submit"
      pill
      class="bg-orange border border-orange text-white hover:bg-orange-dark"
      disabled={$loading}>Add Users</Button
    >
    <Button
      type="button"
      pill
      class="bg-blue-light-50 border rounded-full border-blue-dark-40 text-blue-dark-50 hover:bg-blue-light-40 ml-4"
      disabled={$loading}
      on:click={() => dispatch('cancel')}
      on:touchstart={() => dispatch('cancel')}>Cancel</Button
    >
  </div>
</form>
