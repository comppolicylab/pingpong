<script lang="ts">
  import { invalidateAll } from '$app/navigation';
  import * as api from '$lib/api';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import { happyToast, sadToast } from '$lib/toast';
  import {
    Button,
    Heading,
    Input,
    Label,
    Modal,
    P,
    Table,
    TableBody,
    TableBodyCell,
    TableBodyRow,
    TableHead,
    TableHeadCell,
    Textarea,
    Tooltip
  } from 'flowbite-svelte';
  import { ArrowRightOutline, QuestionCircleOutline } from 'flowbite-svelte-icons';
  export let data;
  $: externalProviders = data.externalProviders;

  let editModalOpen = false;
  let providerToEdit: api.ExternalLoginProvider | null = null;
  const openEditModal = (provider_id: number) => {
    providerToEdit = externalProviders.find((provider) => provider.id === provider_id) || null;
    providerToEditIcon = providerToEdit?.icon || '';
    if (!providerToEdit) {
      sadToast('Could not find provider to edit.');
      return;
    }
    editModalOpen = true;
  };
  let providerToEditIcon = '';

  const handleSubmit = async (event: Event) => {
    event.preventDefault();
    if (!providerToEdit) return;

    const formData = new FormData(event.target as HTMLFormElement);
    const updatedProvider = {
      display_name: formData.get('display_name') as string,
      icon: formData.get('icon') as string,
      description: formData.get('description') as string
    };

    const result = await api.updateExternalLoginProvider(fetch, providerToEdit.id, updatedProvider);
    const response = api.expandResponse(result);
    if (response.error) {
      sadToast(response.error.detail || 'An unknown error occurred');
    } else {
      happyToast(`Provider updated successfully.`);
      providerToEdit = null;
      providerToEditIcon = '';
      invalidateAll();
      editModalOpen = false;
    }
  };
</script>

<div class="relative h-full w-full flex flex-col">
  <PageHeader>
    <div slot="left">
      <h2 class="text-3xl text-color-blue-dark-50 font-serif font-bold px-4 pb-3 pt-6">
        External Login Providers
      </h2>
    </div>
    <div slot="right">
      <a
        href={`/admin`}
        class="text-sm text-blue-dark-50 font-medium bg-white rounded-full p-2 px-4 hover:text-blue-dark-100 hover:bg-blue-dark-40 hover:text-white transition-all"
        >Admin page <ArrowRightOutline size="md" class="text-orange inline-block ml-1" /></a
      >
    </div>
  </PageHeader>
  <div class="h-full w-full overflow-y-auto p-12">
    <div class="flex flex-row flex-wrap justify-between mb-4 items-center gap-y-4">
      <Heading
        tag="h2"
        class="text-3xl font-serif font-medium text-dark-blue-40 shrink-0 max-w-max mr-5"
        >Manage External Login Providers</Heading
      >
      <div class="flex flex-col gap-4">
        <P>
          PingPong supports log in and user syncing functionality with a number of External Login
          Providers. We've included External Login Providers your users have set up below. You can
          manage how each Provider will be presented to users in their Profile.
        </P>
        <Table>
          <TableHead class="bg-blue-light-40 p-1 text-blue-dark-50 tracking-wide rounded-2xl">
            <TableHeadCell
              ><div class="flex flex-row gap-1 items-center">
                ID
                <div>
                  <QuestionCircleOutline color="gray" />
                  <Tooltip
                    type="custom"
                    arrow={false}
                    class="flex flex-row overflow-y-auto bg-gray-900 z-10 max-w-xs py-2 px-3 text-sm text-wrap font-light text-white"
                  >
                    <div class="normal-case whitespace-normal">
                      <p>Used for identification purposes and not displayed to users.</p>
                    </div>
                  </Tooltip>
                </div>
              </div></TableHeadCell
            >
            <TableHeadCell class="w-1/5">Display Name</TableHeadCell>
            <TableHeadCell>Icon</TableHeadCell>
            <TableHeadCell class="w-2/5">Description</TableHeadCell>
            <TableHeadCell></TableHeadCell>
          </TableHead>
          <TableBody>
            {#each externalProviders as provider}
              <TableBodyRow>
                <TableBodyCell class="font-light font-mono">{provider.name}</TableBodyCell>
                <TableBodyCell class="font-light text-wrap"
                  >{#if provider.display_name}
                    {provider.display_name}
                  {:else}
                    <span class="italic">No Display Name</span>
                  {/if}
                </TableBodyCell>
                <TableBodyCell>
                  {#if provider.icon}
                    <img src={provider.icon} alt={provider.display_name} class="size-auto" />
                  {:else}
                    <span class="font-light italic">No Icon</span>
                  {/if}
                </TableBodyCell>
                <TableBodyCell class="font-light text-wrap"
                  >{#if provider.description}
                    {provider.description}
                  {:else}
                    <span class="italic">No Description</span>
                  {/if}
                </TableBodyCell>
                <TableBodyCell tdClass="w-max-w">
                  <Button
                    pill
                    size="sm"
                    class="text-xs mx-2 border-blue-dark-40 text-blue-dark-40 shrink-0 flex flex-row gap-1.5 items-center justify-center bg-white rounded-full p-1 px-3 hover:text-blue-dark-100 hover:bg-blue-dark-40 hover:text-white transition-all max-w-max border"
                    on:click={() => openEditModal(provider.id)}
                  >
                    Edit
                  </Button>
                  <Modal
                    bind:open={editModalOpen}
                    size="sm"
                    on:close={() => (providerToEdit = null)}
                  >
                    <form class="flex flex-col space-y-6 pb-4" action="#" on:submit={handleSubmit}>
                      <h3 class="mb-2 text-xl font-medium text-gray-900 dark:text-white">
                        Editing properties for <span class="font-mono">{providerToEdit?.name}</span>
                      </h3>
                      <Label class="space-y-2">
                        <span>Display Name</span>
                        <Input
                          type="text"
                          id="display_name"
                          name="display_name"
                          placeholder="Acme SSO"
                          value={providerToEdit?.display_name}
                        />
                      </Label>
                      <Label class="space-y-2">
                        <div class="flex flex-row gap-1">
                          <span>Icon Link</span>
                          <div>
                            <QuestionCircleOutline color="gray" />
                            <Tooltip
                              type="custom"
                              arrow={false}
                              class="flex flex-row overflow-y-auto bg-gray-900 z-10 max-w-xs py-2 px-3 text-sm text-wrap font-light text-white"
                            >
                              <div class="normal-case whitespace-normal">
                                <p>Add a link or valid PingPong static endpoint</p>
                              </div>
                            </Tooltip>
                          </div>
                        </div>
                        <Input type="text" name="icon" bind:value={providerToEditIcon} />
                      </Label>
                      {#if providerToEditIcon}
                        <div class="flex flex-col items-center gap-2">
                          <img
                            src={providerToEditIcon}
                            alt={providerToEdit?.display_name}
                            class="max-h-12 size-auto max-w-2/3"
                          />
                          <P class="text-sm text-gray-500 dark:text-gray-300">Preview</P>
                        </div>
                      {/if}
                      <Label class="space-y-2">
                        <span>Description</span>
                        <Textarea
                          id="description"
                          name="description"
                          placeholder="Your SSO identifier when logging in through Acme..."
                          rows="3"
                          value={providerToEdit?.description}
                        />
                      </Label>
                      <div class="flex justify-center">
                        <Button
                          type="submit"
                          class="bg-orange-dark text-white rounded-full hover:bg-orange w-fit"
                          >Save</Button
                        >
                      </div>
                    </form>
                  </Modal>
                </TableBodyCell>
              </TableBodyRow>
            {/each}
          </TableBody>
        </Table>
      </div>
    </div>
  </div>
</div>
