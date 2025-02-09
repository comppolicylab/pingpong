<script lang="ts">
  import { invalidateAll } from '$app/navigation';
  import * as api from '$lib/api';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import { happyToast, sadToast } from '$lib/toast';
  import {
    Button,
    Checkbox,
    Heading,
    Helper,
    Hr,
    Input,
    Label,
    Modal,
    Table,
    TableBody,
    TableBodyCell,
    TableBodyRow,
    TableHead,
    TableHeadCell,
    Toggle,
    Tooltip
  } from 'flowbite-svelte';
  import {
    ArrowRightOutline,
    CheckOutline,
    PlusOutline,
    QuestionCircleOutline
  } from 'flowbite-svelte-icons';

  export let data;

  $: userAgreements = data.agreements;
  $: userCategories = data.categories;

  let editModalOpen = false;
  let categoryToEdit: api.UserAgreementCategory | null = null;
  const openEditModal = (category_id: number) => {
    categoryToEdit = userCategories.find((category) => category.id === category_id) || null;
    if (!categoryToEdit) {
      sadToast('Could not find category to edit.');
      return;
    }
    editModalOpen = true;
  };

  const handleActiveStatusChange = async (event: Event, agreementId: number) => {
    const target = event.target as HTMLInputElement;
    let activate = target.checked;
    const rawAgreement = await api.updateUserAgreement(fetch, agreementId, { active: activate });
    const agreementResponse = api.expandResponse(rawAgreement);
    if (agreementResponse.error) {
      return sadToast(
        agreementResponse.error.detail ||
          `Unknown error ${activate ? 'activating' : 'deactivating'} agreement`
      );
    }
    happyToast('Agreement status updated');
    await invalidateAll();
  };

  const submitCategoryChange = async (event: Event) => {
    event.preventDefault();
    if (!categoryToEdit) return;

    const formData = new FormData(event.target as HTMLFormElement);
    const updatedCategory = {
      name: formData.get('display_name') as string,
      show_all: formData.get('show_all') === 'on'
    };

    const result = await api.updateUserAgreementCategory(fetch, categoryToEdit.id, updatedCategory);
    const response = api.expandResponse(result);
    if (response.error) {
      sadToast(response.error.detail || 'An unknown error occurred');
    } else {
      happyToast(`Agreement Type updated successfully.`);
      categoryToEdit = null;
      invalidateAll();
      editModalOpen = false;
    }
  };
</script>

<div class="relative h-full w-full flex flex-col">
  <PageHeader>
    <div slot="left">
      <h2 class="text-3xl text-color-blue-dark-50 font-serif font-bold px-4 py-3">
        User Agreements
      </h2>
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
    <div class="flex flex-row flex-wrap justify-between mb-4 items-center gap-y-4">
      <Heading
        tag="h2"
        class="text-3xl font-serif font-medium text-dark-blue-40 shrink-0 max-w-max mr-5"
        >Manage User Agreements</Heading
      >
      <Button
        pill
        size="sm"
        class="flex flex-row gap-2 bg-white text-blue-dark-40 border-solid border border-blue-dark-40 hover:text-white hover:bg-blue-dark-40"
        href="/admin/terms/new"><PlusOutline />New Agreement</Button
      >
    </div>
    <div class="flex flex-col gap-4">
      {#each data.categories as category}
        {@const userAgreements_ = userAgreements.filter(
          (agreement) => agreement.category.id === category.id
        )}
        <div class="flex flex-col gap-2">
          <Heading tag="h3" class="text-2xl font-serif font-medium text-dark-blue-40">
            {category.name}
          </Heading>
          <Table class="w-full overflow-visible">
            <TableHead class="bg-blue-light-40 p-1 text-blue-dark-50 tracking-wide rounded-2xl">
              <TableHeadCell>Agreement Name</TableHeadCell>
              <TableHeadCell>Effective Date</TableHeadCell>
              <TableHeadCell>Always Display</TableHeadCell>
              <TableHeadCell>Show to...</TableHeadCell>
              <TableHeadCell>Active</TableHeadCell>
              <TableHeadCell></TableHeadCell>
            </TableHead>
            <TableBody>
              {#each userAgreements_ as agreement}
                <TableBodyRow>
                  <TableBodyCell class="py-2 font-medium whitespace-normal"
                    >{agreement.name}</TableBodyCell
                  >
                  <TableBodyCell class="py-2 font-normal whitespace-normal">
                    {new Date(agreement.effective_date).toLocaleDateString()}
                  </TableBodyCell>
                  <TableBodyCell class="flex flex-row gap-2 py-2 font-normal whitespace-normal">
                    {#if agreement.always_display || agreement.category.show_all}<CheckOutline
                      />{#if !agreement.always_display && agreement.category.show_all}
                        <QuestionCircleOutline color="gray" />
                        <Tooltip
                          type="custom"
                          arrow={false}
                          class="flex flex-row bg-gray-900 z-10 py-2 px-3 text-sm text-wrap font-light text-white"
                        >
                          <div class="normal-case whitespace-normal">
                            <p>
                              Enforced by {agreement.category.name}'s <i>Show All Agreements</i> property
                            </p>
                          </div>
                        </Tooltip>{/if}{/if}
                  </TableBodyCell>
                  <TableBodyCell class="py-2 font-normal whitespace-normal">
                    {#if agreement.apply_to_all}All users
                    {:else}Some users
                    {/if}
                  </TableBodyCell>
                  <TableBodyCell class="py-2">
                    <Toggle
                      color="blue"
                      checked={agreement.active}
                      on:change={(event) => handleActiveStatusChange(event, agreement.id)}
                    />
                  </TableBodyCell>
                  <TableBodyCell class="py-2">
                    <Button
                      pill
                      size="sm"
                      class="text-xs border border-blue-dark-40 text-blue-dark-40 shrink-0 flex flex-row gap-1.5 items-center justify-center bg-white rounded-full p-1 px-3 hover:text-white hover:bg-blue-dark-40 transition-all w-fit"
                      href={`/admin/terms/${agreement.id}`}
                    >
                      Edit
                    </Button>
                  </TableBodyCell>
                </TableBodyRow>
              {/each}
            </TableBody>
          </Table>
        </div>
      {/each}
    </div>
    <Hr class="my-8" />
    <Heading
      tag="h2"
      class="text-3xl font-serif font-medium text-dark-blue-40 shrink-0 max-w-max mr-5 mb-4"
      >Manage User Agreement Types</Heading
    >
    <div>
      <Table class="w-full">
        <TableHead class="bg-blue-light-40 p-1 text-blue-dark-50 tracking-wide rounded-2xl">
          <TableHeadCell>Type</TableHeadCell>
          <TableHeadCell>Show all agreements</TableHeadCell>
          <TableHeadCell></TableHeadCell>
        </TableHead>
        <TableBody>
          {#each data.categories as category}
            <TableBodyRow>
              <TableBodyCell class="py-2 font-medium whitespace-normal"
                >{category.name}</TableBodyCell
              >
              <TableBodyCell class="py-2 font-normal whitespace-normal">
                {#if category.show_all}<CheckOutline />{/if}
              </TableBodyCell>
              <TableBodyCell class="py-2">
                <Button
                  pill
                  size="sm"
                  class="text-xs border border-blue-dark-40 text-blue-dark-40 shrink-0 flex flex-row gap-1.5 items-center justify-center bg-white rounded-full p-1 px-3 hover:text-white hover:bg-blue-dark-40 transition-all w-fit"
                  on:click={() => openEditModal(category.id)}
                >
                  Edit
                </Button>
              </TableBodyCell>
            </TableBodyRow>
          {/each}
        </TableBody>
      </Table>
    </div>
  </div>
</div>

<Modal bind:open={editModalOpen} size="sm" on:close={() => (categoryToEdit = null)}>
  <form class="flex flex-col space-y-6 pb-4" action="#" on:submit={submitCategoryChange}>
    <h3 class="mb-2 text-xl font-medium text-gray-900 dark:text-white">
      Editing properties for <span class="font-medium">{categoryToEdit?.name}</span>
    </h3>
    <Label class="space-y-2">
      <span>Type Name</span>
      <Input type="text" id="display_name" name="display_name" value={categoryToEdit?.name} />
    </Label>
    <Label class="space-y-2">
      <span>Show All Agreements</span>
      <Helper class="mb-2"
        >By default, only the latest agreement will be shown for users to read and agree to. When
        enabled, all agreements with this agreement type will be shown to users sequentially.</Helper
      >
      <Checkbox id="show_all" name="show_all" checked={categoryToEdit?.show_all}
        >Require users to agree to all agreements of this agreement type.</Checkbox
      >
    </Label>
    <div class="flex justify-center">
      <Button type="submit" class="bg-orange-dark text-white rounded-full hover:bg-orange w-fit"
        >Save</Button
      >
    </div>
  </form>
</Modal>
