<script lang="ts">
  import { onMount } from 'svelte';
  import {
    CheckCircleOutline,
    CloseOutline,
    EnvelopeOutline,
    QuestionCircleOutline,
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
    Select,
    type LinkType,
    Tooltip
  } from 'flowbite-svelte';
  import { SearchOutline } from 'flowbite-svelte-icons';
  import { ROLES, ROLE_LABELS_INHERIT_ADMIN } from '$lib/api';
  import type { ClassUser, Role, ClassUsersResponse } from '$lib/api';
  import { sadToast, happyToast } from '$lib/toast';
  import * as api from '$lib/api';
  import { submitParentForm } from '$lib/form';
  import CanvasLogo from './CanvasLogo.svelte';

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

  const rolePermissions: Record<Role, number> = {
    admin: 3,
    teacher: 2,
    student: 1
  };

  export let currentUserRole: Role | null = null;
  export let currentUserId: number | null = null;

  /**
   * Check if the current user has permission to edit the role of a user.
   *
   * @param role The role of the user to check.
   * @returns True if the current user can edit the role, false otherwise.
   */
  const checkUserEditPermissions = (role: Role | null) => {
    let currentPermissionLevel = currentUserRole ? rolePermissions[currentUserRole] : 0;
    let editPermissionLevel = role ? rolePermissions[role] : 0;
    return editPermissionLevel <= currentPermissionLevel;
  };

  const isCurrentUser = (user: ClassUser) => {
    return user.id === currentUserId;
  };

  // The list of role options for the dropdown selector
  const roleOptions = [
    ...ROLES.filter((role) => role !== 'admin' && checkUserEditPermissions(role)).map((role) => ({
      value: role,
      name: ROLE_LABELS_INHERIT_ADMIN[role]
    })),
    // Need a value for "no access" role, dropdown defaults to Select a Role otherwise
    { value: null, name: 'No Group Role' }
  ];

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
   * Get a list of roles for a user.
   *
   * Technically, roles are independent of each other, which means that a user
   * can be defined to multiple roles. Roles can also be inherited through the
   * permissions model (such as inheriting class admin permissions from
   * institutional admin permissions).
   *
   * To simplify the UI, we try to pretend roles are mutually exclusive. This
   * function identifies the "primary" role for a user, which is the most
   * permissive role, as well as any other roles the user has.
   *
   * Currently, we can't tell if the role is inherited or assigned directly. If
   * the role is inherited, we can't revoke it directly in this UI.
   *
   * @param user The user to get role information for.
   * @returns An object with the primary role and any other roles the user has.
   */
  const getRoleInfoForUser = (user: ClassUser) => {
    // Roles in order of most permissive to least.
    // Administrator roles are only inherited, so they are not shown in the dropdown UI.
    const priorityRoles: Role[] = ['teacher', 'student'];
    const allRoles: Role[] = ['admin', 'teacher', 'student'];
    // The primary role is the one the user is granted that has maximal permissions.
    const primary = priorityRoles.find((role) => user.roles[role]);
    const other = allRoles.filter((role) => user.roles[role] && role !== primary);
    return {
      primary: primary || (other[0] !== 'admin' ? other[0] : null) || null,
      label: primary ? ROLE_LABELS_INHERIT_ADMIN[primary] : 'No Group Role',
      other,
      otherLabels: other.map((role) => ROLE_LABELS_INHERIT_ADMIN[role])
    };
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
    let role: Role | null = null;
    role = (d.role.toString() as Role) || null;
    const userId = parseInt(d.user_id.toString(), 10);

    if (!d.user_id) {
      showErrorAndForceCurrentDataRefresh('Failed to update user role: user ID is missing');
      return;
    }

    if (!classId) {
      showErrorAndForceCurrentDataRefresh('Failed to update user role: class ID is missing');
      return;
    }

    const roleLabel = ROLE_LABELS_INHERIT_ADMIN[role as Role] || role || 'No Group Role';
    const user = users.find((u) => u.id === +userId);
    const userName = user?.name || user?.email || `User ${userId}`;
    const action = `Set ${userName} group role to "${roleLabel}"`;

    const result = await api.updateClassUserRole(fetch, classId, userId, {
      role: role || null
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
      showErrorAndForceCurrentDataRefresh('Failed to remove user: group ID is missing');
      return;
    }

    const user = users.find((u) => u.id === +userId);
    const userName = user?.name || user?.email || `User ${userId}`;
    const result = await api.removeClassUser(fetch, classId, userId);

    if (api.isErrorResponse(result)) {
      // Force a re-render of the component with the current data
      const detail = result.detail || 'unknown error';
      showErrorAndForceCurrentDataRefresh(`Failed to remove user ${userName}: ${detail}`);
    } else {
      happyToast(`Removed ${userName} from the group`);
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
    <Table divClass="relative overflow-x-auto overflow-y-show">
      <TableHead>
        <TableHeadCell padding={thPad}>User</TableHeadCell>
        <TableHeadCell padding={thPad}>Role</TableHeadCell>
        <TableHeadCell padding={thPad}>Status</TableHeadCell>
        <TableHeadCell padding={thPad}></TableHeadCell>
      </TableHead>
      <TableBody>
        {#each users as user (user.id)}
          {@const roleInfo = getRoleInfoForUser(user)}
          {@const noPermissions = !checkUserEditPermissions(roleInfo.primary)}
          {@const currentUser = isCurrentUser(user)}
          <TableBodyRow>
            <TableBodyCell {tdClass}
              ><div class="flex flex-col">
                <div>{user.name}</div>
                <div class="font-normal">{user.has_real_name ? user.email : ''}</div>
              </div></TableBodyCell
            >
            <TableBodyCell {tdClass}>
              {#if noPermissions || currentUser || user.lms_type}
                <div class="flex flex-row justify-between">
                  <div class="flex flex-col">
                    <div>{roleInfo.label}</div>
                    {#if roleInfo.other.length > 0}
                      <div
                        class="text-xs whitespace-normal font-light text-pretty text-gray-500 mt-2"
                      >
                        * {noPermissions || user.lms_type ? 'This user is' : 'You are'} also assigned
                        to the following roles:
                        <span class="font-medium">{roleInfo.otherLabels.join(', ')}</span>
                      </div>
                    {/if}
                  </div>
                  <div>
                    <QuestionCircleOutline color="gray" />
                    <Tooltip
                      type="custom"
                      arrow={false}
                      class="flex flex-row overflow-y-auto bg-gray-900 z-10 max-w-xs py-2 px-3 text-sm text-wrap font-light text-white"
                    >
                      <div class="whitespace-normal">
                        <span class="font-medium">Role Change Not Allowed:</span>{' '}
                        {noPermissions
                          ? `You do not have enough permissions to change ${roleInfo.label} user roles.`
                          : currentUser
                            ? 'You cannot change your own user role.'
                            : 'You cannot edit roles for imported users. Please make changes in Canvas.'}
                      </div>
                    </Tooltip>
                  </div>
                </div>
              {:else}
                <form on:submit={submitUpdateUser}>
                  <input type="hidden" name="user_id" value={user.id} />
                  <Select
                    name="role"
                    items={roleOptions}
                    value={roleInfo.primary}
                    placeholder="Select a user role..."
                    on:change={submitParentForm}
                  />
                </form>
                {#if !roleInfo.primary && roleInfo.other.length === 0}
                  <div class="text-xs whitespace-normal font-light text-pretty text-gray-500 mt-2">
                    * This user is not assigned to any role currently.
                  </div>
                {:else if roleInfo.other.length > 0}
                  <div class="text-xs whitespace-normal font-light text-pretty text-gray-500 mt-2">
                    * This user is also assigned to the following roles: <span class="font-medium"
                      >{roleInfo.otherLabels.join(', ')}</span
                    >
                  </div>
                {/if}
              {/if}
            </TableBodyCell>
            <TableBodyCell {tdClass}>
              <div class="flex flex-row items-center gap-2">
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
                {#if user.lms_type === 'canvas'}
                  <div title="This user was imported from Canvas.">
                    <span class="text-red-600"><CanvasLogo size="5" /></span>
                  </div>
                {/if}
              </div>
            </TableBodyCell>
            <TableBodyCell {tdClass}>
              {#if !(currentUser || user.lms_type || noPermissions)}
                <form on:submit={submitRemoveUser}>
                  <input type="hidden" name="user_id" value={user.id} />
                  <Button on:click={deleteUser}><TrashBinOutline color="red" /></Button>
                </form>
              {/if}
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
