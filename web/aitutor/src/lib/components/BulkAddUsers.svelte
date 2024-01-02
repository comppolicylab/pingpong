<script lang="ts">
  import {createEventDispatcher} from 'svelte';
  import * as api from '$lib/api';
  import {Select, Helper, Button, GradientButton, Label, Textarea, Hr} from "flowbite-svelte";

  export let role;
  export let title;

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
    <Select id="role" name="role" value="{role}" items="{roles}" />

    <Label for="title">Title</Label>
    <Select id="title" name="title" value="{title}" items="{titles}" />
  </div>
  <Hr />
  <div>
    <GradientButton type="submit" color="cyanToBlue">Add Users</GradientButton>
    <Button type="button" color="red" on:click="{() => dispatch('cancel')}">Cancel</Button>
  </div>
</form>
