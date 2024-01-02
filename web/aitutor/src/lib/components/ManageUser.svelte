<script lang="ts">
  import {createEventDispatcher} from 'svelte';
  import * as api from '$lib/api';
  import {Hr, GradientButton, Label, Select, Input, Button} from "flowbite-svelte";
  export let user = null;

  const dispatch = createEventDispatcher();

  const action = user ? '?/updateUser' : '?/createUser';

  const roles = Array.from(api.ROLES.entries()).map(([value, name]) => ({ value, name }));
  const titles = api.TITLES.map((name) => ({ value: name, name }));
</script>

<form {action} method="POST" class="w-96 mx-auto">
  <div class="space-y-2">
  <Label for="email">Email</Label>
  <Input label="Email" disabled={!!user} type="email" id="email" name="email" value="{user?.email}" />
  <Label for="role">Role</Label>
  <Select label="Role" id="role" name="role" items="{roles}" value="{user?.role}" />
  <Label for="title">Title</Label>
  <Select label="Title" id="title" name="title" items="{titles}" value="{user?.title}" />
  {#if user}
    <input type="hidden" name="user_id" value="{user.id}" />
  {/if}
  </div>

  <Hr />

  <div>
    <GradientButton type="submit" color="cyanToBlue">Save</GradientButton>
    <Button type="button" color="red" on:click="{() => dispatch('cancel')}">Cancel</Button>
  </div>

</form>
