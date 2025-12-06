<script lang="ts">
  import {
    Button,
    Heading,
    Modal,
    Table,
    TableBody,
    TableBodyCell,
    TableBodyRow,
    TableHead,
    TableHeadCell,
    Input,
    Label
  } from 'flowbite-svelte';
  import { ArrowRightOutline, PlusOutline, FileCopyOutline, PenSolid } from 'flowbite-svelte-icons';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import type { Institution } from '$lib/api';
  import * as api from '$lib/api';
  import { happyToast, sadToast } from '$lib/toast';

  export let data;

  const sortInstitutions = (items: Institution[]) =>
    [...items].sort((a, b) => a.name.localeCompare(b.name));

  let institutions: Institution[] = sortInstitutions(data.institutions);
  let createModalOpen = false;
  let newInstitutionName = '';
  let creating = false;
  let copyModalOpen = false;
  let copyInstitutionId: number | null = null;
  let copyInstitutionName = '';
  let copying = false;

  const handleCreate = async () => {
    const trimmed = newInstitutionName.trim();
    if (!trimmed) {
      sadToast('Please enter an institution name.');
      return;
    }
    creating = true;
    const response = api.expandResponse(await api.createInstitution(fetch, { name: trimmed }));
    creating = false;
    if (response.error || !response.data) {
      sadToast(response.error?.detail || 'Unable to create institution.');
      return;
    }
    happyToast('Institution created');
    institutions = sortInstitutions([...institutions, response.data]);
    newInstitutionName = '';
    createModalOpen = false;
  };

  const openCopyModal = (inst: Institution) => {
    copyInstitutionId = inst.id;
    copyInstitutionName = `${inst.name} (Copy)`;
    copyModalOpen = true;
  };

  const handleCopy = async () => {
    if (!copyInstitutionId) return;
    const trimmed = copyInstitutionName.trim();
    if (!trimmed) {
      sadToast('Please enter a name for the copy.');
      return;
    }
    copying = true;
    const response = api.expandResponse(
      await api.copyInstitution(fetch, copyInstitutionId, { name: trimmed })
    );
    copying = false;
    if (response.error || !response.data) {
      sadToast(response.error?.detail || 'Unable to copy institution.');
      return;
    }
    happyToast('Institution copied');
    institutions = sortInstitutions([...institutions, response.data]);
    copyModalOpen = false;
    copyInstitutionId = null;
    copyInstitutionName = '';
  };
</script>

<div class="relative h-full w-full flex flex-col">
  <PageHeader>
    <div slot="left">
      <h2 class="text-3xl text-color-blue-dark-50 font-serif font-bold px-4 py-3">Institutions</h2>
    </div>
    <div slot="right">
      <a
        href={`/admin`}
        class="text-sm text-blue-dark-50 font-medium bg-white rounded-full p-2 px-4 hover:text-white hover:bg-blue-dark-40 transition-all flex items-center gap-2"
        >Admin page <ArrowRightOutline size="md" class="text-orange" /></a
      >
    </div>
  </PageHeader>

  <div class="h-full w-full overflow-y-auto p-12">
    <div class="flex flex-row flex-wrap justify-between mb-6 items-center gap-y-4">
      <Heading
        tag="h2"
        class="text-3xl font-serif font-medium text-dark-blue-40 shrink-0 max-w-max mr-5"
        >Manage Institutions</Heading
      >
      <Button
        pill
        size="sm"
        class="flex flex-row gap-2 bg-white text-blue-dark-40 border-solid border border-blue-dark-40 hover:text-white hover:bg-blue-dark-40"
        on:click={() => (createModalOpen = true)}><PlusOutline />New Institution</Button
      >
    </div>

    <div class="flex flex-col gap-4">
      <Table class="w-full">
        <TableHead class="bg-blue-light-40 p-1 text-blue-dark-50 tracking-wide rounded-2xl">
          <TableHeadCell>Institution Name</TableHeadCell>
          <TableHeadCell></TableHeadCell>
        </TableHead>
        <TableBody>
          {#if institutions.length === 0}
            <TableBodyRow>
              <TableBodyCell colspan={2} class="text-sm text-gray-500 py-4">
                No institutions found.
              </TableBodyCell>
            </TableBodyRow>
          {/if}

          {#each institutions as institution}
            <TableBodyRow>
              <TableBodyCell class="py-2 font-medium whitespace-normal">
                {institution.name}
              </TableBodyCell>
              <TableBodyCell class="py-2 text-right">
                <div class="flex gap-2 justify-end">
                  <Button
                    pill
                    size="sm"
                    class="text-xs border border-blue-dark-40 text-blue-dark-40 shrink-0 flex flex-row gap-1.5 items-center justify-center bg-white rounded-full p-1 px-3 hover:text-white hover:bg-blue-dark-40 transition-all w-fit"
                    href={`/admin/institutions/${institution.id}`}
                  >
                    <PenSolid size="sm" class="mr-1" />
                    Edit
                  </Button>
                  <Button
                    pill
                    size="sm"
                    class="text-xs border border-blue-dark-40 text-blue-dark-40 shrink-0 flex flex-row gap-1.5 items-center justify-center bg-white rounded-full p-1 px-3 hover:text-white hover:bg-blue-dark-40 transition-all w-fit"
                    on:click={() => openCopyModal(institution)}
                  >
                    <FileCopyOutline size="sm" class="mr-1" />
                    Copy
                  </Button>
                </div>
              </TableBodyCell>
            </TableBodyRow>
          {/each}
        </TableBody>
      </Table>
    </div>
  </div>
</div>

<Modal bind:open={createModalOpen} size="md" on:close={() => (newInstitutionName = '')}>
  <div class="space-y-6 p-4">
    <Heading tag="h3" class="text-xl font-semibold text-gray-900">New Institution</Heading>
    <div class="flex flex-col gap-2">
      <Label for="institution-name" class="text-xs uppercase tracking-wide text-gray-600"
        >Institution name</Label
      >
      <Input
        id="institution-name"
        name="institution-name"
        placeholder="Example University"
        bind:value={newInstitutionName}
      />
    </div>
    <div class="flex justify-end gap-3">
      <Button color="light" on:click={() => (createModalOpen = false)}>Cancel</Button>
      <Button
        class="bg-orange text-white rounded-full hover:bg-orange-dark"
        disabled={creating || !newInstitutionName.trim()}
        on:click={handleCreate}
      >
        Create
      </Button>
    </div>
  </div>
</Modal>

<Modal bind:open={copyModalOpen} size="md" on:close={() => (copyInstitutionName = '')}>
  <div class="space-y-6 p-4">
    <Heading tag="h3" class="text-xl font-semibold text-gray-900">Copy Institution</Heading>
    <div class="flex flex-col gap-2">
      <Label for="copy-institution-name" class="text-xs uppercase tracking-wide text-gray-600"
        >New name</Label
      >
      <Input
        id="copy-institution-name"
        name="copy-institution-name"
        placeholder="Institution name (Copy)"
        bind:value={copyInstitutionName}
      />
    </div>
    <div class="flex justify-end gap-3">
      <Button color="light" on:click={() => (copyModalOpen = false)}>Cancel</Button>
      <Button
        class="bg-orange text-white rounded-full hover:bg-orange-dark"
        disabled={copying || !copyInstitutionName.trim()}
        on:click={handleCopy}
      >
        Copy
      </Button>
    </div>
  </div>
</Modal>
