<script lang="ts">
  import { onMount } from 'svelte';
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
    Input,
    Button,
    Pagination,
    type LinkType
  } from 'flowbite-svelte';
  import { SearchOutline } from 'flowbite-svelte-icons';
  import Toggle from '$lib/components/Toggle.svelte';
  import type { ToggleChangeEvent } from '$lib/components/Toggle.svelte';
  import { ROLES, ROLE_LABELS } from '$lib/api';
  import type { ClassUser, Role, ClassUsersResponse } from '$lib/api';
  import { sadToast, happyToast } from '$lib/toast';
  import * as api from '$lib/api';

  /**
   * Number of users to view on each page.
   */
  export let pageSize: number = 10;

  /**
   * The current class id.
   */
  export let classId: number;

  /**
   * Function to fetch users from the server.
   */
  export let fetchUsers: (page: number, pageSize: number, search?: string) => ClassUsersResponse;

  /**
   * Style class for the table data cells.
   */
  export let tdClass = 'px-3 py-2 whitespace-nowrap font-medium';

  /**
   * Style class for the table header cells.
   */
  export let thPad = 'px-3 py-2';

  // Whether a request is in flight.
  let loading = false;
  // The current list of users.
  let users: ClassUser[] = [];
  // The current page (1-based index).
  let page = 1;
  // The total number of users in the full (unpaginated) resultset.
  let total = 0;
  // The current search query.
  let search = '';
  // The list of pagination links to show.
  let pages: Array<LinkType> = [];
  // The index of the first user on the current page.
  $: startIdx = Math.min(total, Math.max(0, (page - 1) * pageSize + 1));
  // The index of the last user on the current page.
  $: endIdx = Math.min(startIdx + pageSize - 1, total);

  /**
   * Fetch users from the server based on component state.
   */
  const loadUsers = async () => {
    loading = true;
    const response = await fetchUsers(page, pageSize, search);
    if (response.error) {
      sadToast(`Failed to load users: ${response.error.detail || 'unknown error'}`);
      return;
    }
    users = response.users;
    total = response.total;
    loading = false;

    // Figure out 5 pages to show in the pagination component.
    // The current page should be in the middle of the list of pages.
    const totalPages = Math.ceil(total / pageSize);
    let start = Math.max(1, page - 2);
    const end = Math.min(totalPages, start + 4);
    // Adjust start to make sure there are 5 pages in total if possible
    start = Math.max(1, end - 4);

    pages = Array.from({ length: end - start + 1 }, (_, i) => ({
      name: `${start + i}`,
      active: start + i === page
    }));
  };

  /**
   * Load a specific page of users.
   *
   * This function clamps the page to the bounds.
   */
  const loadPage = (p: number, force: boolean = false) => {
    if (p < 1) {
      p = 1;
    } else if (p > Math.ceil(total / pageSize)) {
      p = Math.ceil(total / pageSize);
    }

    if (!force && p === page) {
      return;
    }

    page = p;
    loadUsers();
  };

  /**
   * Handle clicking on a page number in the pagination component.
   */
  const handleClick = (evt: MouseEvent) => {
    const num = +((evt.target as HTMLDivElement).innerText || '1');
    if (isNaN(num)) {
      return;
    }
    loadPage(num);
  };

  /**
   * Load the previous page of users.
   */
  const loadPreviousPage = () => loadPage(page - 1);

  /**
   * Load the next page of users.
   */
  const loadNextPage = () => loadPage(page + 1);

  /**
   * Reload the user list from the beginning.
   */
  const refresh = () => loadPage(1, true);

  /**
   * Remove a user from the class.
   */
  const deleteUser = (evt: MouseEvent) => {
    const target = evt.currentTarget as HTMLButtonElement;
    if (confirm('Are you sure you want to remove this user?')) {
      target?.form?.requestSubmit();
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
   * Force a re-render of the component with the current data.
   */
  const showErrorAndForceCurrentDataRefresh = (detail: string) => {
    sadToast(detail);
    users = users.slice();
  };

  /**
   * Submit the form to update the user role.
   */
  const submitUpdateUser = async (evt: SubmitEvent) => {
    evt.preventDefault();

    const form = evt.target as HTMLFormElement;
    const formData = new FormData(form);
    const d = Object.fromEntries(formData.entries());

    const role = d.role.toString() as Role;
    if (!role) {
      showErrorAndForceCurrentDataRefresh('Failed to update user role: role is missing');
      return;
    }

    const userId = parseInt(d.user_id.toString(), 10);
    if (!d.user_id) {
      showErrorAndForceCurrentDataRefresh('Failed to update user role: user ID is missing');
      return;
    }

    if (!classId) {
      showErrorAndForceCurrentDataRefresh('Failed to update user role: class ID is missing');
      return;
    }

    const roleLabel = ROLE_LABELS[role as Role] || role;
    const user = users.find((u) => u.id === +userId)?.email || `User ${userId}`;
    const action =
      d.verdict === 'on'
        ? `Added ${user} to the ${roleLabel} group`
        : `Removed ${user} from the ${roleLabel} group`;

    const result = await api.updateClassUser(fetch, classId, userId, {
      role: role,
      verdict: d.verdict === 'on' ? true : false
    });

    if (api.isErrorResponse(result)) {
      // Force a re-render of the component with the current data
      const detail = result.detail || 'unknown error';
      showErrorAndForceCurrentDataRefresh(`Failed to update user role: ${detail}`);
    } else {
      happyToast(action);
    }
  };

  /**
   * Remove a user from the class.
   */
  const submitRemoveUser = async (evt: SubmitEvent) => {
    evt.preventDefault();

    const form = evt.target as HTMLFormElement;
    const formData = new FormData(form);
    const d = Object.fromEntries(formData.entries());

    const userId = parseInt(d.user_id.toString(), 10);
    if (!d.user_id) {
      showErrorAndForceCurrentDataRefresh('Failed to remove user: user ID is missing');
      return;
    }

    if (!classId) {
      showErrorAndForceCurrentDataRefresh('Failed to remove user: class ID is missing');
      return;
    }

    const user = users.find((u) => u.id === +userId)?.email || `User ${userId}`;
    const result = await api.removeClassUser(fetch, classId, userId);

    if (api.isErrorResponse(result)) {
      // Force a re-render of the component with the current data
      const detail = result.detail || 'unknown error';
      showErrorAndForceCurrentDataRefresh(`Failed to remove user: ${detail}`);
    } else {
      happyToast(`Removed ${user} from the class`);
      loadUsers();
    }
  };

  // Load users from the server when the component is mounted.
  onMount(async () => {
    await loadUsers();
  });
</script>

<div class="my-2">
  <Input type="text" placeholder="Search users by email" bind:value={search} on:keyup={refresh}>
    <SearchOutline slot="left" class="w-6 h-6 text-gray-500 dark:text-gray-400" />
  </Input>
</div>
<div class="relative">
  {#if loading}
    <div
      class="absolute top-0 left-0 w-full h-full flex flex-col gap-4 items-center justify-center bg-white bg-opacity-90 dark:bg-black dark:bg-opacity-90 z-10"
    >
      <div class="text-gray-500 animate-pulse">Loading users...</div>
    </div>
  {/if}

  {#if users.length === 0}
    <div class="text-center text-gray-500 dark:text-gray-400">No users found</div>
  {:else}
    <Table>
      <TableHead>
        <TableHeadCell padding={thPad}>Email</TableHeadCell>
        {#each ROLES as role}
          <TableHeadCell padding={thPad}>{ROLE_LABELS[role]}</TableHeadCell>
        {/each}
        <TableHeadCell padding={thPad}>Verified</TableHeadCell>
        <TableHeadCell padding={thPad}></TableHeadCell>
      </TableHead>
      <TableBody>
        {#each users as user (user.id)}
          <TableBodyRow>
            <TableBodyCell {tdClass}>{user.email}</TableBodyCell>
            {#each ROLES as role}
              <TableBodyCell {tdClass}>
                <form on:submit={submitUpdateUser}>
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
            <TableBodyCell {tdClass}>
              {#if user.state === 'verified'}
                <div title="This user is verified."><CheckCircleOutline color="green" /></div>
              {:else if user.state === 'unverified'}
                <div title="This user has not responded to the invitation.">
                  <EnvelopeOutline color="orange" />
                </div>
              {:else if user.state === 'banned'}
                <div title="This user has been banned from PingPong.">
                  <CloseOutline color="red" />
                </div>
              {:else}
                {user.state}
              {/if}
            </TableBodyCell>
            <TableBodyCell {tdClass}>
              <form on:submit={submitRemoveUser}>
                <input type="hidden" name="user_id" value={user.id} />
                <Button on:click={deleteUser}><TrashBinOutline color="red" /></Button>
              </form>
            </TableBodyCell>
          </TableBodyRow>
        {/each}
      </TableBody>
    </Table>
  {/if}
</div>
<div class="flex flex-col items-center justify-center gap-2">
  <div class="text-sm text-gray-700 dark:text-gray-400">
    Showing <span class="font-semibold text-gray-900 dark:text-white">{startIdx}</span>
    to
    <span class="font-semibold text-gray-900 dark:text-white">{endIdx}</span>
    of
    <span class="font-semibold text-gray-900 dark:text-white">{total}</span>
    {total === 1 ? 'user' : 'users'}
  </div>
  <Pagination
    {pages}
    on:previous={loadPreviousPage}
    on:next={loadNextPage}
    on:click={handleClick}
  />
</div>
