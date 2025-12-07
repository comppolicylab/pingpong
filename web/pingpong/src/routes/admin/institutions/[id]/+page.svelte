<script lang="ts">
  import { invalidateAll } from '$app/navigation';
  import {
    Button,
    Heading,
    Helper,
    Input,
    Label,
    Table,
    TableBody,
    TableBodyCell,
    TableBodyRow,
    TableHead,
    TableHeadCell
  } from 'flowbite-svelte';
  import { ArrowRightOutline, PlusOutline, TrashBinOutline } from 'flowbite-svelte-icons';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import * as api from '$lib/api';
  import { happyToast, sadToast } from '$lib/toast';
  import { loading } from '$lib/stores/general.js';
  import { resolve } from '$app/paths';

  export let data;

  let institution: api.InstitutionWithAdmins = data.institution;
  let draftName = institution.name;
  let newAdminEmail = '';
  let savingName = false;
  let managingAdmins: Record<number, boolean> = {};

  const sortAdmins = (admins: api.InstitutionAdmin[]) =>
    [...admins].sort((a, b) =>
      (a.name || a.email || '').localeCompare(b.name || b.email || '', undefined, {
        sensitivity: 'base'
      })
    );

  const sortInstitutionAdmins = (inst: api.InstitutionWithAdmins) => ({
    ...inst,
    admins: sortAdmins(inst.admins),
    root_admins: sortAdmins(inst.root_admins)
  });

  institution = sortInstitutionAdmins(institution);

  const refresh = async () => {
    const response = await api
      .getInstitutionWithAdmins(fetch, institution.id)
      .then(api.expandResponse);
    if (response.error || !response.data) {
      sadToast(response.error?.detail || 'Unable to refresh institution');
      return;
    }
    institution = sortInstitutionAdmins(response.data);
    draftName = institution.name;
    newAdminEmail = '';
    managingAdmins = {};
  };

  const saveName = async () => {
    const trimmed = draftName.trim();
    if (!trimmed || trimmed === institution.name) return;
    savingName = true;
    try {
      const response = api.expandResponse(
        await api.updateInstitution(fetch, institution.id, { name: trimmed })
      );
      if (response.error) {
        sadToast(response.error.detail || 'Could not update name');
        return;
      }
      happyToast('Institution renamed');
      await refresh();
      await invalidateAll();
    } catch (err) {
      console.error(err);
      sadToast('Could not update name');
    } finally {
      savingName = false;
    }
  };

  const addAdmin = async () => {
    const trimmed = newAdminEmail.trim();
    if (!trimmed) {
      sadToast('Enter an email address.');
      return;
    }
    managingAdmins[-1] = true;
    try {
      const response = api.expandResponse(
        await api.addInstitutionAdmin(fetch, institution.id, { email: trimmed })
      );
      if (response.error) {
        sadToast(response.error.detail || 'Could not add admin');
        return;
      }
      happyToast('Admin added');
      await refresh();
    } catch (err) {
      console.error(err);
      sadToast('Could not add admin');
    } finally {
      managingAdmins = { ...managingAdmins, [-1]: false };
    }
  };

  const removeAdmin = async (userId: number) => {
    managingAdmins = { ...managingAdmins, [userId]: true };
    try {
      const response = api.expandResponse(
        await api.removeInstitutionAdmin(fetch, institution.id, userId)
      );
      if (response.error) {
        sadToast(response.error.detail || 'Could not remove admin');
        return;
      }
      happyToast('Admin removed');
      await refresh();
    } catch (err) {
      console.error(err);
      sadToast('Could not remove admin');
    } finally {
      managingAdmins = { ...managingAdmins, [userId]: false };
    }
  };
</script>

<div class="relative h-full w-full flex flex-col">
  <PageHeader>
    <div slot="left">
      <h2 class="text-3xl text-color-blue-dark-50 font-serif font-bold px-4 py-3">Institutions</h2>
    </div>
    <div slot="right">
      <a
        href={resolve(`/admin/institutions`)}
        class="text-sm text-blue-dark-50 font-medium bg-white rounded-full p-2 px-4 hover:text-white hover:bg-blue-dark-40 transition-all flex items-center gap-2"
        >All Institutions <ArrowRightOutline size="md" class="text-orange" /></a
      >
    </div>
  </PageHeader>
  <div class="h-full w-full overflow-y-auto p-12 space-y-8">
    <div class="flex flex-row flex-wrap justify-between mb-4 items-center gap-y-4">
      <Heading
        tag="h2"
        class="text-3xl font-serif font-medium text-dark-blue-40 shrink-0 max-w-max mr-5"
        >Edit Institution</Heading
      >
    </div>
    <div>
      <Label for="name" class="mb-1">Institution Name</Label>
      <Helper class="mb-2"
        >This name will be used to identify institutions on the Admin page and Manage Group pages.</Helper
      >
      <Input
        type="text"
        name="name"
        id="name"
        placeholder="Institution name"
        bind:value={draftName}
        disabled={$loading || savingName}
        on:change={saveName}
      />
    </div>
    <div class="space-y-4">
      <Heading tag="h4" class="text-xl font-serif font-medium text-dark-blue-40">
        Institutional Admins
      </Heading>
      <Table class="w-full">
        <TableHead class="bg-blue-light-40 p-1 text-blue-dark-50 tracking-wide rounded-2xl">
          <TableHeadCell>Name</TableHeadCell>
          <TableHeadCell>Email</TableHeadCell>
          <TableHeadCell></TableHeadCell>
        </TableHead>
        <TableBody>
          {#if institution.admins.length === 0}
            <TableBodyRow>
              <TableBodyCell colspan={3} class="text-sm text-gray-500 py-3">
                No institutional admins yet.
              </TableBodyCell>
            </TableBodyRow>
          {/if}
          {#each institution.admins as admin (admin.id)}
            <TableBodyRow>
              <TableBodyCell class="py-2 font-medium whitespace-normal">
                {admin.name || 'Unknown'}
              </TableBodyCell>
              <TableBodyCell class="py-2 font-normal whitespace-normal">
                {admin.email || 'N/A'}
              </TableBodyCell>
              <TableBodyCell class="py-2">
                <Button
                  pill
                  size="sm"
                  class="text-xs border border-red-200 text-red-700 shrink-0 flex flex-row gap-1.5 items-center justify-center bg-white rounded-full p-1 px-3 hover:text-white hover:bg-red-600 transition-all w-fit"
                  disabled={!!managingAdmins[admin.id]}
                  on:click={() => removeAdmin(admin.id)}
                >
                  <TrashBinOutline size="sm" class="mr-1" />
                  Remove
                </Button>
              </TableBodyCell>
            </TableBodyRow>
          {/each}
        </TableBody>
      </Table>

      <div class="bg-blue-50 border border-blue-100 rounded-xl p-4 flex flex-col gap-3 max-w-3xl">
        <Label class="text-xs uppercase tracking-wide text-blue-900">Add admin by email</Label>
        <div class="flex flex-row gap-3">
          <Input
            type="email"
            placeholder="admin@example.edu"
            class="sm:flex-1"
            bind:value={newAdminEmail}
            name="admin-email"
          />
          <Button
            on:click={addAdmin}
            disabled={!!managingAdmins[-1] || !newAdminEmail.trim()}
            class="px-3 bg-blue-dark-40 text-white rounded-full hover:bg-blue-dark-50"
          >
            <PlusOutline class="mr-2" />
            Add admin
          </Button>
        </div>
      </div>
    </div>

    <div class="space-y-3">
      <Heading tag="h4" class="text-xl font-serif font-medium text-dark-blue-40">
        Root Admins (inherited)
      </Heading>
      <Table class="w-full">
        <TableHead class="bg-gray-100 p-1 text-gray-700 tracking-wide rounded-2xl">
          <TableHeadCell>Name</TableHeadCell>
          <TableHeadCell>Email</TableHeadCell>
        </TableHead>
        <TableBody>
          {#if institution.root_admins.length === 0}
            <TableBodyRow>
              <TableBodyCell colspan={2} class="text-sm text-gray-500 py-3">
                No root admins configured.
              </TableBodyCell>
            </TableBodyRow>
          {/if}
          {#each institution.root_admins as admin (admin.id)}
            <TableBodyRow>
              <TableBodyCell class="py-2 font-medium whitespace-normal">
                {admin.name || 'Unknown'}
              </TableBodyCell>
              <TableBodyCell class="py-2 font-normal whitespace-normal">
                {admin.email || 'N/A'}
              </TableBodyCell>
            </TableBodyRow>
          {/each}
        </TableBody>
      </Table>
    </div>
  </div>
</div>
