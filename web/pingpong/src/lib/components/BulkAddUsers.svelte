<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import * as api from '$lib/api';
  import { Select, Helper, Button, Label, Textarea, Hr } from 'flowbite-svelte';
  import { writable } from 'svelte/store';
  import { sadToast } from '$lib/toast';

  export let role: api.Role;

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

    const request: api.CreateClassUsersRequest = {
      roles: emailList.map((e) => ({
        email: e,
        roles: {
          admin: role === 'admin',
          teacher: role === 'teacher',
          student: role === 'student'
        }
      }))
    };

    dispatch('submit', request);
  };

  const roles = api.ROLES.map((role) => ({ value: role, name: api.ROLE_LABELS[role] }));
</script>

<form on:submit={submitForm}>
  <div class="space-y-2">
    <Label for="emails">Emails</Label>
    <Helper>Enter email addresses separated by commas or newlines.</Helper>
    <Textarea id="emails" name="emails" rows="3" />

    <Label for="role">Role</Label>
    <Helper>
      <div>Choose a role to grant permissions to these users to view the group.</div>
      <ul class="list-disc pl-8 my-2">
        <li>
          <strong>Members</strong> can create chats and view their own personal chat history.
        </li>
        <li>
          <strong>Moderators</strong> can view everyone's chat history and manage members.
        </li>
        <li>
          <strong>Administrators</strong> can view everyone's chat history and manage the group.
        </li>
      </ul>
    </Helper>
    <Select id="role" name="role" value={role} items={roles} />
  </div>
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
