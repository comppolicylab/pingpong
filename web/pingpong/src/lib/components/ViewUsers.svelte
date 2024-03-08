<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import { enhance } from '$app/forms';
  import type { SubmitFunction } from '@sveltejs/kit';
  import {
    CheckCircleOutline,
    CloseOutline,
    EnvelopeOutline,
    TrashBinOutline
  } from 'flowbite-svelte-icons';
  import {
    Table,
    TableBody,
    TableBodyCell,
    TableBodyRow,
    TableHead,
    TableHeadCell,
    TableSearch,
    Button
  } from 'flowbite-svelte';
  import Toggle from '$lib/components/Toggle.svelte';
  import type { ToggleChangeEvent } from '$lib/components/Toggle.svelte';
  import { ROLES, ROLE_LABELS } from '$lib/api';
  import type { ClassUser, Role } from '$lib/api';
  import { sadToast, happyToast } from '$lib/toast';

  const dispatch = createEventDispatcher();

  /**
   * List of users to display in the class.
   */
  export let users: ClassUser[];

  // User search query
  let needle = '';
  $: filteredUsers = users
    .filter((user) => user.email.includes(needle))
    .sort((a, b) => a.email.localeCompare(b.email));

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
  const updateUserRole = (evt: ToggleChangeEvent) => {
    const target = evt.detail.target;
    // Set the value of the verdict input to "on" or "off" based on the checked state of the toggle
    target.form?.requestSubmit();
  };

  /**
   * Fancy updates for user role toggles.
   */
  const enhanceToggle: SubmitFunction = ({ formData }) => {
    const role = formData.get('role');
    if (!role) {
      sadToast('Failed to update user role: role is missing');
      return;
    }
    const userId = formData.get('user_id');
    if (!userId) {
      sadToast('Failed to update user role: user ID is missing');
      return;
    }
    const roleLabel = ROLE_LABELS[role as Role] || role;
    const user = users.find((u) => u.id === +userId)?.email || `User ${userId}`;
    const action =
      formData.get('verdict') === 'on'
        ? `Added ${user} to the ${roleLabel} group`
        : `Removed ${user} from the ${roleLabel} group`;
    return async ({ result, update }) => {
      if (result.type === 'failure') {
        // Force a re-render of the component with the current data
        const detail = result.data?.detail || 'unknown error';
        sadToast(`Failed to update user role: ${detail}`);
        users = users.slice();
      } else {
        happyToast(action);
        update();
      }
    };
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
            <form action="?/updateUser" method="POST" use:enhance={enhanceToggle}>
              <input type="hidden" name="user_id" value={user.id} />
              <input type="hidden" name="role" value={role} />
              <Toggle
                checked={user.roles[role] || false}
                on:change={updateUserRole}
                name="verdict"
              />
            </form>
          </TableBodyCell>
        {/each}
        <TableBodyCell>
          {#if user.state === 'verified'}
            <div title="This user is verified."><CheckCircleOutline color="green" /></div>
          {:else if user.state === 'unverified'}
            <div title="This user has not responded to the invitation.">
              <EnvelopeOutline color="orange" />
            </div>
          {:else if user.state === 'banned'}
            <div title="This user has been banned from PingPong."><CloseOutline color="red" /></div>
          {:else}
            {user.state}
          {/if}
        </TableBodyCell>
        <TableBodyCell>
          <form action="?/removeUser" method="POST" use:enhance>
            <input type="hidden" name="user_id" value={user.id} />
            <Button type="submit" on:click={deleteUser.bind(null, user.id)}
              ><TrashBinOutline color="red" /></Button
            >
          </form>
        </TableBodyCell>
      </TableBodyRow>
    {/each}
  </TableBody>
</Table>
