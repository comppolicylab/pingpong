<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import * as api from '$lib/api';
  import { Select, Helper, Button, GradientButton, Label, Textarea, Hr } from 'flowbite-svelte';

  export let role: string;
  export let title: string = '';

  const dispatch = createEventDispatcher();

  const roles = Array.from(api.ROLES.entries()).map(([value, name]) => ({ value, name }));
  const titles = api.TITLES.map((name) => ({ value: name, name }));
</script>

<form action="?/createUsers" method="POST">
  <div class="space-y-2">
    <Label for="emails">Emails</Label>
    <Helper>Enter email addresses separated by commas or newlines.</Helper>
    <Textarea id="emails" name="emails" rows="3" />

    <Label for="role">Role</Label>
    <Helper>
      <div>Choose a role to grant permissions to these users to view the class.</div>
      <ul>
        <li>Students will have permission to view the class and chat history.</li>
        <li>
          Teachers will have permission to create new chats, view everyone's chat history, and
          perform some management tasks.
        </li>
        <li>Admins have full control to manage the class and also see everyone's chat history.</li>
      </ul>
    </Helper>
    <Select id="role" name="role" value={role} items={roles} />
    <input type="hidden" name="title" value={title} />
  </div>
  <Hr />
  <div>
    <GradientButton type="submit" color="cyanToBlue">Add Users</GradientButton>
    <Button
      type="button"
      color="red"
      on:click={() => dispatch('cancel')}
      on:touchstart={() => dispatch('cancel')}>Cancel</Button
    >
  </div>
</form>
