<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import * as api from '$lib/api';
  import { Select, Helper, Button, Label, Textarea, Hr } from 'flowbite-svelte';

  export let role: api.Role;

  const dispatch = createEventDispatcher();

  const roles = api.ROLES.map((role) => ({ value: role, name: api.ROLE_LABELS[role] }));
</script>

<form action="?/createUsers" method="POST">
  <div class="space-y-2">
    <Label for="emails">Emails</Label>
    <Helper>Enter email addresses separated by commas or newlines.</Helper>
    <Textarea id="emails" name="emails" rows="3" />

    <Label for="role">Role</Label>
    <Helper>
      <div>Choose a role to grant permissions to these users to view the class.</div>
      <ul class="list-disc pl-8 my-2">
        <li>
          <strong>Students</strong> can create chats and view their own personal chat history.
        </li>
        <li>
          <strong>Teachers</strong> can view everyone's chat history and manage students.
        </li>
        <li><strong>Admins</strong> can view everyone's chat history and manage the class.</li>
      </ul>
    </Helper>
    <Select id="role" name="role" value={role} items={roles} />
  </div>
  <Hr />
  <div>
    <Button
      type="submit"
      pill
      class="bg-orange border border-orange text-white hover:bg-orange-dark">Add Users</Button
    >
    <Button
      type="button"
      pill
      class="bg-blue-light-50 border rounded-full border-blue-dark-40 text-blue-dark-50 hover:bg-blue-light-40 ml-4"
      on:click={() => dispatch('cancel')}
      on:touchstart={() => dispatch('cancel')}>Cancel</Button
    >
  </div>
</form>
