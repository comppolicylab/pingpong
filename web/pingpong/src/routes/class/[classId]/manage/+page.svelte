<script lang="ts">
  import { onMount } from 'svelte';
  import { writable } from 'svelte/store';
  import type { Writable } from 'svelte/store';
  import { page } from '$app/stores';
  import { beforeNavigate } from '$app/navigation';
  import * as api from '$lib/api';
  import type { FileUploadInfo, Assistant, ServerFile } from '$lib/api';
  import {
    Button,
    Checkbox,
    Helper,
    Modal,
    Secondary,
    Card,
    Heading,
    Label,
    Input
  } from 'flowbite-svelte';
  import BulkAddUsers from '$lib/components/BulkAddUsers.svelte';
  import ViewUsers from '$lib/components/ViewUsers.svelte';
  import ManageAssistant from '$lib/components/ManageAssistant.svelte';
  import ViewAssistant from '$lib/components/ViewAssistant.svelte';
  import FileUpload from '$lib/components/FileUpload.svelte';
  import FilePlaceholder from '$lib/components/FilePlaceholder.svelte';
  import Info from '$lib/components/Info.svelte';
  import { PenOutline, CloudArrowUpOutline } from 'flowbite-svelte-icons';
  import { sadToast, happyToast } from '$lib/toast';
  import { humanSize } from '$lib/size';

  /**
   * Application data.
   */
  export let data;

  /**
   * Form submission.
   */
  export let form;

  /**
   * Max upload size as a nice string.
   */
  $: maxUploadSize = humanSize(data.uploadInfo.class_file_max_size);

  onMount(() => {
    // Show an error if the form failed
    // TODO -- more universal way of showing validation errors
    if (!form || !form.$status) {
      return;
    }

    if (form.$status >= 400) {
      let msg = form.detail || 'An unknown error occurred';
      if (form?.field) {
        msg += ` (${form.field})`;
      }
      sadToast(msg);
    } else if (form.$status >= 200 && form.$status < 300) {
      happyToast('Success!');
    }
  });

  let usersModalOpen = false;
  let anyCanCreateAsst = data?.class.any_can_create_assistant || false;
  let anyCanPublishAsst = data.class.any_can_publish_assistant || false;
  let anyCanPublishThread = data?.class.any_can_publish_thread || false;
  let anyCanUploadClassFile = data?.class.any_can_upload_class_file || false;

  let assistants: Assistant[] = [];
  const blurred = writable(true);
  let uploads = writable<FileUploadInfo[]>([]);
  const trashFiles = writable<number[]>([]);
  let savingAssistant = false;
  $: publishOptMakesSense = anyCanCreateAsst;
  $: apiKey = data.apiKey || '';
  $: apiKeyBlur =
    apiKey.substring(0, 6) + '**************' + apiKey.substring(Math.max(6, apiKey.length - 6));
  $: editingAssistant = parseInt($page.url.searchParams.get('edit-assistant') || '0', 10);
  $: creators = data?.assistantCreators || {};
  $: {
    assistants = data?.assistants || [];
    assistants.sort((a, b) => a.name.localeCompare(b.name));
  }
  $: models = data?.models || [];
  $: files = data?.files || [];
  $: allFiles = [
    ...$uploads,
    ...files.map((f) => ({
      state: 'success',
      progress: 100,
      file: { type: f.content_type, name: f.name },
      response: f,
      promise: Promise.resolve(f)
    }))
  ]
    .filter((f) => !$trashFiles.includes((f.response as ServerFile)?.id))
    .sort((a, b) => {
      const aName = a.file?.name || (a.response as { name: string })?.name || '';
      const bName = b.file?.name || (b.response as { name: string })?.name || '';
      return aName.localeCompare(bName);
    }) as FileUploadInfo[];
  $: asstFiles = allFiles
    .filter((f) => f.state === 'success')
    .map((f) => f.response) as ServerFile[];

  $: hasApiKey = !!data?.class?.api_key;

  $: canEditClassInfo = !!data?.grants?.canEditInfo;
  $: canManageClassUsers = !!data?.grants?.canManageUsers;
  $: canUploadClassFiles = !!data?.grants?.canUploadClassFiles;
  $: canViewApiKey = !!data?.grants?.canViewApiKey;
  $: canCreateAssistant = !!data?.grants?.canCreateAssistants;
  $: canPublishAssistant = !!data?.grants?.canPublishAssistants;
  $: isAdmin = !!data?.grants?.isAdmin;

  // Check if we are editing an assistant and prompt if so.
  beforeNavigate((nav) => {
    const isSaved = nav.to?.url.searchParams.has('save');

    if (isSaved) {
      nav.to?.url.searchParams.delete('save');
      return;
    }

    if (editingAssistant && !savingAssistant) {
      const really = confirm(
        'You have not saved your changes to this assistant. Do you wish to discard them?'
      );
      if (!really) {
        nav.cancel();
      }
    }
  });

  // Handle file deletion.
  const removeFile = async (evt: CustomEvent<FileUploadInfo>) => {
    const file = evt.detail;
    if (file.state === 'pending' || file.state === 'deleting') {
      return;
    } else if (file.state === 'error') {
      uploads.update((u) => u.filter((f) => f !== file));
    } else {
      $trashFiles = [...$trashFiles, (file.response as ServerFile).id];
      const result = await api.deleteFile(fetch, data.class.id, (file.response as ServerFile).id);
      if (result.$status >= 300) {
        $trashFiles = $trashFiles.filter((f) => f !== (file.response as ServerFile).id);
        sadToast(`Failed to delete file: ${result.detail || 'unknown error'}`);
      }
    }
  };

  // Handle adding new files
  const handleNewFiles = (evt: CustomEvent<Writable<FileUploadInfo[]>>) => {
    uploads = evt.detail;
  };
  // Submit file upload
  const uploadFile = (f: File, onProgress: (p: number) => void) => {
    return api.uploadFile(data.class.id, f, { onProgress });
  };

  /**
   * Function to fetch users from the server.
   */
  const fetchUsers = async (page: number, pageSize: number, search?: string) => {
    const limit = pageSize;
    const offset = Math.max(0, (page - 1) * pageSize);
    return api.getClassUsers(fetch, data.class.id, { limit, offset, search });
  };
</script>

<div
  class="container py-8 space-y-12 divide-y-3 divide-blue-dark-40 dark:divide-gray-700 overflow-y-auto w-full flex flex-col justify-between h-[calc(100%-5rem)]"
>
  <Heading tag="h2" class="text-3xl font-serif pt-8 text-blue-dark-40">Manage Class</Heading>
  {#if canEditClassInfo}
    <form action="?/updateClass" class="pt-6" method="POST">
      <div class="grid grid-cols-3 gap-x-6 gap-y-8">
        <div>
          <Heading customSize="text-xl" tag="h3"
            ><Secondary class="text-3xl text-black font-normal">Class Details</Secondary></Heading
          >
          <Info>General information about the class.</Info>
        </div>
        <div>
          <Label for="name">Name</Label>
          <Input label="Name" id="name" name="name" value={data.class.name} />
        </div>

        <div>
          <Label for="term">Term</Label>
          <Input label="Term" id="term" name="term" value={data.class.term} />
        </div>

        <div></div>
        <div>
          <Checkbox
            id="any_can_publish_thread"
            name="any_can_publish_thread"
            checked={anyCanPublishThread}>Allow anyone to publish threads</Checkbox
          >
        </div>
        <Helper
          >When this is enabled, anyone in the class can share their own threads with the rest of
          the class. Otherwise, only teachers and admins can share threads.</Helper
        >

        <div></div>
        <Checkbox
          id="any_can_create_assistant"
          name="any_can_create_assistant"
          bind:checked={anyCanCreateAsst}>Allow anyone to create assistants</Checkbox
        >
        <Helper
          >When this is enabled, anyone in the class can create assistants. Otherwise, only teachers
          and admins can create assistants.</Helper
        >

        <div></div>
        {#if publishOptMakesSense}
          <Checkbox
            id="any_can_publish_assistant"
            name="any_can_publish_assistant"
            checked={anyCanPublishAsst}
          >
            Allow anyone to publish assistants
          </Checkbox>
        {:else}
          <Checkbox
            id="any_can_publish_assistant"
            name="any_can_publish_assistant"
            checked={false}
            disabled
          >
            Allow anyone to publish assistants
          </Checkbox>
        {/if}

        <Helper
          >When this is enabled, anyone in the class can share their own assistants with the rest of
          the class. Otherwise, only teachers and admins can share assistants.</Helper
        >

        <div></div>
        {#if publishOptMakesSense}
          <Checkbox
            id="any_can_upload_class_file"
            name="any_can_upload_class_file"
            checked={anyCanUploadClassFile}>Allow anyone to upload files for assistants</Checkbox
          >
        {:else}
          <Checkbox
            id="any_can_upload_class_file"
            name="any_can_upload_class_file"
            checked={false}
            disabled>Allow anyone to upload files for assistants</Checkbox
          >
        {/if}
        <Helper
          >When this is enabled, anyone in the class can upload files for use in creating
          assistants. Otherwise, only teachers and admins can upload files. (Note that users can
          still upload files privately to chat threads even when this setting is disabled.)</Helper
        >

        <div></div>
        <div></div>
        <div>
          <Button pill type="submit" class="bg-orange text-white hover:bg-orange-dark">Save</Button>
        </div>
      </div>
    </form>
  {/if}

  {#if canViewApiKey}
    <form action="?/updateApiKey" class="pt-6" method="POST">
      <div class="grid grid-cols-3 gap-x-6 gap-y-8">
        <div>
          <Heading customSize="text-xl font-bold" tag="h3"
            ><Secondary class="text-3xl text-black font-normal">Billing</Secondary></Heading
          >
          <Info>Manage OpenAI credentials</Info>
        </div>

        <div class="col-span-2">
          <Label for="apiKey">API Key</Label>
          <div class="w-full relative" class:cursor-pointer={$blurred}>
            <Input
              autocomplete="off"
              class={$blurred ? 'cursor-pointer' : undefined}
              label="API Key"
              id="apiKey"
              name="apiKey"
              value={apiKey}
              on:blur={() => ($blurred = true)}
              on:focus={() => ($blurred = false)}
            />
            {#if $blurred}
              <div
                class="cursor-pointer flex items-center gap-2 w-full h-full absolute top-0 left-0 bg-white font-mono pointer-events-none"
              >
                {#if hasApiKey}
                  <span>{apiKeyBlur}</span>
                {:else}
                  <span class="text-gray-400">No API key set</span>
                {/if}
                <PenOutline size="sm" />
              </div>
            {/if}
          </div>

          {#if apiKey && !$blurred}
            <Helper
              >Note: changing the API key will break all threads and assistants in the class, so it
              is not currently supported.</Helper
            >
          {/if}
        </div>

        <div></div>
        <div></div>
        <div>
          <Button pill type="submit" class="bg-orange text-white hover:bg-orange-dark">Save</Button>
        </div>
      </div>
    </form>
  {/if}

  {#if canManageClassUsers}
    <div class="grid grid-cols-3 gap-x-6 gap-y-8 pt-6">
      <div>
        <Heading customSize="text-xl font-bold" tag="h3"
          ><Secondary class="text-3xl text-black font-normal">Users</Secondary></Heading
        >
        <Info>Manage users who have access to this class.</Info>
      </div>
      <div class="col-span-2">
        <div class="mb-4">
          <ViewUsers {fetchUsers} />
        </div>
        <Button
          pill
          class="bg-orange text-white hover:bg-orange-dark"
          on:click={() => {
            usersModalOpen = true;
          }}
          on:touchstart={() => {
            usersModalOpen = true;
          }}>Invite new users</Button
        >
        {#if usersModalOpen}
          <Modal bind:open={usersModalOpen} title="Manage users">
            <BulkAddUsers on:cancel={() => (usersModalOpen = false)} role="student" />
          </Modal>
        {/if}
      </div>
    </div>
  {/if}

  {#if canUploadClassFiles}
    <div class="grid grid-cols-3 gap-x-6 gap-y-8 pt-6">
      <div>
        <Heading tag="h3" customSize="text-xl font-bold"
          ><Secondary class="text-3xl text-black font-normal">Files</Secondary></Heading
        >
        <Info
          >Upload files for use in assistants. Files must be under {maxUploadSize}. See the
          <a
            href="https://platform.openai.com/docs/api-reference/files/create"
            rel="noopener noreferrer"
            target="_blank">OpenAI API docs</a
          > for more information.
        </Info>
      </div>
      <div class="col-span-2">
        {#if !hasApiKey}
          <div class="text-gray-400 mb-4">
            You need to set an API key before you can upload files.
          </div>
        {:else}
          <div class="my-4">
            <FileUpload
              drop
              accept={data.uploadInfo.fileTypes({ code_interpreter: true, retrieval: true })}
              maxSize={data.uploadInfo.class_file_max_size}
              upload={uploadFile}
              on:change={handleNewFiles}
              on:error={(e) => sadToast(e.detail.message)}
            >
              <CloudArrowUpOutline size="lg" slot="icon" class="text-gray-500" />
              <span slot="label" class="ml-2 text-gray-500"
                >Click or drag & drop to upload files.</span
              >
            </FileUpload>
          </div>
          <div class="flex gap-2 flex-wrap">
            {#each allFiles as file}
              <FilePlaceholder
                mimeType={data.uploadInfo.mimeType}
                info={file}
                on:delete={removeFile}
              />
            {/each}
          </div>
        {/if}
      </div>
    </div>
  {/if}

  <div class="grid grid-cols-3 gap-x-6 gap-y-8 pt-6">
    <div>
      <Heading tag="h3" customSize="text-xl font-bold"
        ><Secondary class="text-3xl text-black font-normal">AI Assistants</Secondary></Heading
      >
      <Info>Manage AI assistants.</Info>
    </div>
    <div class="col-span-2 flex flex-wrap gap-4">
      {#if !hasApiKey}
        <div class="text-gray-400 mb-4">
          You need to set an API key before you can create AI assistants.
        </div>
      {:else}
        {#each assistants as assistant}
          {#if assistant.id == editingAssistant}
            <Card class="w-full max-w-full">
              <form
                class="grid grid-cols-2 gap-2"
                action="?/updateAssistant"
                method="POST"
                on:submit={() => (savingAssistant = true)}
              >
                <ManageAssistant
                  files={asstFiles}
                  getFileSupportFilter={data.uploadInfo.getFileSupportFilter}
                  {assistant}
                  {models}
                  canPublish={canPublishAssistant || false}
                />
              </form>
            </Card>
          {:else}
            <Card
              class="w-full max-w-full space-y-2"
              href={(isAdmin || assistant.creator_id === data.me.user?.id) && canCreateAssistant
                ? `${$page.url.pathname}?edit-assistant=${assistant.id}`
                : null}
            >
              <ViewAssistant {assistant} creator={creators[assistant.creator_id]} />
            </Card>
          {/if}
        {/each}
        {#if !editingAssistant && canCreateAssistant}
          <Card class="w-full max-w-full">
            <Heading tag="h4" class="pb-3">Add new AI assistant</Heading>
            <form
              class="grid grid-cols-2 gap-2"
              action="?/createAssistant"
              method="POST"
              on:submit={() => (savingAssistant = true)}
            >
              <ManageAssistant
                files={asstFiles}
                {models}
                canPublish={canPublishAssistant || false}
              />
            </form>
          </Card>
        {/if}
      {/if}
    </div>
  </div>
</div>
