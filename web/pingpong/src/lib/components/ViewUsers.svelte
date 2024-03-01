<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import { CheckCircleOutline, CloseOutline, EnvelopeOutline, TrashBinOutline } from 'flowbite-svelte-icons';
  import { Table, TableBody, TableBodyCell, TableBodyRow, TableHead, TableHeadCell, TableSearch, Toggle, Button } from 'flowbite-svelte';
  import { ROLES, ROLE_LABELS } from '$lib/api';
  import type { ClassUser } from '$lib/api';

  const dispatch = createEventDispatcher();

  export let users: ClassUser[];

  // User search query
  let needle = '';
  $: filteredUsers = users.filter((user) => user.email.includes(needle));

  /**
   * Remove a user from the class.
   */
  const deleteUser = (id: number) => {
    if (confirm('Are you sure you want to remove this user?')) {
      dispatch('removeUser', id);
    }
  };

  /**
   * Grant a permission to the user.
   */
  const updateUserRole = (evt: Event) => {
    const target = evt.target as HTMLInputElement
    // Find sibling "verdict" input
    const verdict = target.form?.querySelector('input[name="verdict"]') as HTMLInputElement;
    // Set the value of the verdict input to "on" or "off" based on the checked state of the toggle
    verdict.value = target.checked ? 'on' : 'off';
    target.form?.submit();
  };
</script>

<TableSearch placeholder="Search users by email" bind:inputValue={needle} />
<Table>
  <TableHead>
    <TableHeadCell>Email</TableHeadCell>
    {#each ROLES as role}
      <TableHeadCell>{ROLE_LABELS[role]}</TableHeadCell>
    {/each}
    <TableHeadCell>Verified</TableHeadCell>
    <TableHeadCell></TableHeadCell>
  </TableHead>
  <TableBody>
    {#each filteredUsers as user (user.id)}
      <TableBodyRow>
        <TableBodyCell>{user.email}</TableBodyCell>
        {#each ROLES as role}
          <TableBodyCell>
            <form action="?/updateUser" method="POST">
              <input type="hidden" name="user_id" value={user.id} />
              <input type="hidden" name="role" value={role} />
              <input type="hidden" name="verdict" value={user.roles[role] ? 'on' : 'off'} />
              <Toggle color="green" checked={user.roles[role]} on:change={updateUserRole} />
            </form>
          </TableBodyCell>
        {/each}
        <TableBodyCell>
          {#if user.state === 'verified'}
            <CheckCircleOutline color="green" />
          {:else if user.state === 'unverified'}
            <EnvelopeOutline color="yellow" />
          {:else if user.state === 'banned'}
            <CloseOutline color="red" />
          {:else}
            {user.state}
          {/if}
        </TableBodyCell>
        <TableBodyCell>
          <form action="?/removeUser" method="POST">
            <input type="hidden" name="user_id" value={user.id} />
            <Button type="submit" on:click={deleteUser.bind(null, user.id)}><TrashBinOutline color="red" /></Button>
          </form>
        </TableBodyCell>
      </TableBodyRow>
    {/each}
  </TableBody>
</Table>
