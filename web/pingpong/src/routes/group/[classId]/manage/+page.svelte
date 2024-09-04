<script lang="ts">
  import { onMount } from 'svelte';
  import { writable } from 'svelte/store';
  import type { Writable } from 'svelte/store';
  import dayjs from '$lib/time';
  import * as api from '$lib/api';
  import type {
    FileUploadInfo,
    ServerFile,
    CreateClassUsersRequest,
    LMSClass as CanvasClass
  } from '$lib/api';
  import {
    Button,
    ButtonGroup,
    Checkbox,
    Helper,
    Modal,
    Secondary,
    Heading,
    Label,
    Input,
    Select,
    InputAddon,
    Alert,
    Spinner,
    CloseButton,
    Dropdown,
    DropdownItem
  } from 'flowbite-svelte';
  import BulkAddUsers from '$lib/components/BulkAddUsers.svelte';
  import CanvasLogo from '$lib/components/CanvasLogo.svelte';
  import ViewUsers from '$lib/components/ViewUsers.svelte';
  import FileUpload from '$lib/components/FileUpload.svelte';
  import FilePlaceholder from '$lib/components/FilePlaceholder.svelte';
  import Info from '$lib/components/Info.svelte';
  import {
    PenOutline,
    CloudArrowUpOutline,
    EyeOutline,
    EyeSlashOutline,
    LinkOutline,
    RefreshOutline,
    SortHorizontalOutline,
    AdjustmentsHorizontalOutline,
    UserRemoveSolid,
    ExclamationCircleOutline
  } from 'flowbite-svelte-icons';
  import { sadToast, happyToast } from '$lib/toast';
  import { humanSize } from '$lib/size';
  import { invalidateAll, onNavigate } from '$app/navigation';
  import { browser } from '$app/environment';
  import { submitParentForm } from '$lib/form';
  import { page } from '$app/stores';
  import DropdownContainer from '$lib/components/DropdownContainer.svelte';
  import CanvasClassDropdownOptions from '$lib/components/CanvasClassDropdownOptions.svelte';
  import PermissionsTable from '$lib/components/PermissionsTable.svelte';

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

  const errorMessages: Record<number, string> = {
    1: 'We faced an issue when trying to sync with Canvas.',
    2: 'You denied the request for PingPong to access your Canvas account. Please try again.',
    3: 'Canvas is currently unable to complete the authorization request. Please try again later.',
    4: 'We received an invalid response from Canvas. Please try again.',
    5: 'We were unable to complete the authorization request with Canvas. Please try again.'
  };

  // Function to get error message from error code
  function getErrorMessage(errorCode: number) {
    return (
      errorMessages[errorCode] || 'An unknown error occurred while trying to sync with Canvas.'
    );
  }

  onMount(() => {
    const errorCode = $page.url.searchParams.get('error_code');
    if (errorCode) {
      const errorMessage = getErrorMessage(parseInt(errorCode) || 0);
      sadToast(errorMessage);
    }

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

  /**
   * Format assistant permissions into a string for dropdown selector.
   */
  const formatAssistantPermissions = (classData: api.Class | undefined) => {
    if (!classData) {
      return 'create:0,publish:0,upload:0';
    }

    let create = classData.any_can_create_assistant ? 1 : 0;
    let publish = classData.any_can_publish_assistant ? 1 : 0;
    let upload = classData.any_can_upload_class_file ? 1 : 0;

    return `create:${create},publish:${publish},upload:${upload}`;
  };

  /**
   * Parse assistant permissions from a string.
   */
  const parseAssistantPermissions = (permissions: string) => {
    let parts = permissions.split(',');
    let create = parts[0].split(':')[1] === '1';
    let publish = parts[1].split(':')[1] === '1';
    let upload = parts[2].split(':')[1] === '1';

    return {
      any_can_create_assistant: create,
      any_can_publish_assistant: publish,
      any_can_upload_class_file: upload
    };
  };

  let usersModalOpen = false;
  let anyCanPublishThread = data?.class.any_can_publish_thread || false;
  let makePrivate = data?.class.private || false;
  let assistantPermissions = formatAssistantPermissions(data?.class);
  const asstPermOptions = [
    { value: 'create:0,publish:0,upload:0', name: 'Do not allow members to create' },
    { value: 'create:1,publish:0,upload:1', name: 'Members can create but not publish' },
    { value: 'create:1,publish:1,upload:1', name: 'Members can create and publish' }
  ];

  const blurred = writable(true);
  let uploads = writable<FileUploadInfo[]>([]);
  const trashFiles = writable<number[]>([]);
  $: apiKey = data.apiKey || '';
  $: apiKeyBlur =
    apiKey.substring(0, 6) + '**************' + apiKey.substring(Math.max(6, apiKey.length - 6));
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

  $: hasApiKey = !!data?.class?.api_key;

  $: canEditClassInfo = !!data?.grants?.canEditInfo;
  $: canManageClassUsers = !!data?.grants?.canManageUsers;
  $: canUploadClassFiles = !!data?.grants?.canUploadClassFiles;
  $: canViewApiKey = !!data?.grants?.canViewApiKey;
  let currentUserRole: api.Role | null;
  $: currentUserRole = data.grants?.isAdmin
    ? 'admin'
    : data.grants?.isTeacher
      ? 'teacher'
      : data.grants?.isStudent
        ? 'student'
        : null;

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
   * Bulk add users to a class.
   */
  let timesAdded = 0;
  const submitCreateUsers = async (e: CustomEvent<CreateClassUsersRequest>) => {
    const result = await api.createClassUsers(fetch, data.class.id, e.detail);

    if (api.isErrorResponse(result)) {
      invalidateAll();
      usersModalOpen = false;
      let msg = result.detail || 'An unknown error occurred';
      sadToast(msg);
    } else {
      invalidateAll();
      usersModalOpen = false;
      timesAdded++;
      happyToast('Success!');
    }
  };

  const updatingClass = writable(false);

  /**
   * Save updates to class metadata and permissions.
   */
  const updateClass = async (evt: SubmitEvent) => {
    evt.preventDefault();
    $updatingClass = true;

    const form = evt.target as HTMLFormElement;
    const formData = new FormData(form);
    const d = Object.fromEntries(formData.entries());

    const update: api.UpdateClassRequest = {
      name: d.name.toString(),
      term: d.term.toString(),
      any_can_publish_thread: d.any_can_publish_thread?.toString() === 'on',
      private: d.make_private?.toString() === 'on',
      ...parseAssistantPermissions(d.asst_perm.toString())
    };

    const result = await api.updateClass(fetch, data.class.id, update);
    if (api.isErrorResponse(result)) {
      $updatingClass = false;
      let msg = result.detail || 'An unknown error occurred';
      sadToast(msg);
    } else {
      invalidateAll();
      $updatingClass = false;
      happyToast('Saved group info');
    }
  };

  const updatingApiKey = writable(false);
  // Handle API key update
  const submitUpdateApiKey = async (evt: SubmitEvent) => {
    evt.preventDefault();
    $updatingApiKey = true;

    const form = evt.target as HTMLFormElement;
    const formData = new FormData(form);
    const d = Object.fromEntries(formData.entries());

    if (!d.apiKey) {
      $updatingApiKey = false;
      sadToast('API key cannot be empty');
      return;
    }

    const _apiKey = (d.apiKey as string | undefined) || '';
    const result = await api.updateApiKey(fetch, data.class.id, _apiKey);

    if (api.isErrorResponse(result)) {
      $updatingApiKey = false;
      let msg = result.detail || 'An unknown error occurred';
      sadToast(msg);
    } else {
      invalidateAll();
      $updatingApiKey = false;
      happyToast('Saved API key!');
    }
  };

  /**
   * Function to fetch users from the server.
   */
  const fetchUsers = async (page: number, pageSize: number, search?: string) => {
    const limit = pageSize;
    const offset = Math.max(0, (page - 1) * pageSize);
    return api.getClassUsers(fetch, data.class.id, { limit, offset, search });
  };

  $: classId = data.class.id;
  $: canvasLinkedClass = data.class.lms_class;

  const redirectToCanvas = async () => {
    const result = await api.getCanvasLink(fetch, data.class.id, 'harvard');
    const response = api.expandResponse(result);
    if (response.error) {
      sadToast(response.error.detail || 'An unknown error occurred');
    } else {
      if (browser) {
        window.location.href = response.data.url;
        return { $status: 303, detail: 'Redirecting you to Canvas...' };
      }
    }
  };
  const dismissCanvasSync = async () => {
    const result = await api.dismissCanvasSync(fetch, data.class.id, 'harvard');
    const response = api.expandResponse(result);
    if (response.error) {
      sadToast(response.error.detail || 'An unknown error occurred');
    } else {
      invalidateAll();
    }
  };
  const enableCanvasSync = async () => {
    const result = await api.bringBackCanvasSync(fetch, data.class.id, 'harvard');
    const response = api.expandResponse(result);
    if (response.error) {
      sadToast(response.error.detail || 'An unknown error occurred');
    } else {
      invalidateAll();
    }
  };

  let disconnectCanvas = false;
  let disconnectClass = false;
  let loadedCanvasClasses = writable<CanvasClass[]>([]);
  let canvasClasses: CanvasClass[] = [];
  // The formatted canvas classes loaded from the API.
  $: canvasClasses = $loadedCanvasClasses
    .map((c) => ({
      lms_id: c.lms_id,
      name: c.name || 'Unnamed class',
      course_code: c.course_code || '',
      term: c.term
    }))
    .sort((a, b) => a.course_code.localeCompare(b.course_code));

  // Whether we are currently loading canvas classes from the API.
  let loadingCanvasClasses = false;
  // Load canvas classes from the API.
  const loadCanvasClasses = async () => {
    loadingCanvasClasses = true;
    const result = await api.loadCanvasClasses(fetch, data.class.id, 'harvard');
    const response = api.expandResponse(result);
    if (response.error) {
      loadingCanvasClasses = false;
      invalidateAll();
      sadToast(response.error.detail || 'An unknown error occurred');
    } else {
      $loadedCanvasClasses = response.data.classes;
      loadingCanvasClasses = false;
    }
  };

  // State for the canvas class selection dropdown.
  let classSelectDropdownOpen = false;
  // The canvas class id
  let selectedClass = data.class.lms_class?.toString() || '';

  $: classNameDict = canvasClasses.reduce<{ [key: string]: string }>((acc, class_) => {
    acc[class_.lms_id] = `[${class_.term}] ${class_.course_code}: ${class_.name}`;
    return acc;
  }, {});
  $: selectedClassName = classNameDict[selectedClass] || 'Select a class...';

  const updateSelectedClass = (classValue: string) => {
    classSelectDropdownOpen = false;
    selectedClass = classValue;
  };

  const saveSelectedClass = async () => {
    if (!selectedClass) {
      return;
    }
    const result = await api.saveCanvasClass(fetch, data.class.id, 'harvard', selectedClass);
    const response = api.expandResponse(result);
    if (response.error) {
      sadToast(response.error.detail || 'An unknown error occurred');
    } else {
      invalidateAll();
      happyToast('Canvas class successfully linked!');
    }
  };

  let syncingCanvasClass = false;
  const syncClass = async () => {
    syncingCanvasClass = true;
    const result = await api.syncCanvasClass(fetch, data.class.id, 'harvard');
    const response = api.expandResponse(result);
    if (response.error) {
      // Needed here to update the timer (Last sync: ...)
      syncingCanvasClass = false;
      invalidateAll();
      sadToast(response.error.detail || 'An unknown error occurred');
    } else {
      syncingCanvasClass = false;
      invalidateAll();
      timesAdded++;
      happyToast('Synced PingPong user list with Canvas roster!');
    }
  };

  let editDropdownOpen = false;
  const deleteClassSync = async (keep: boolean) => {
    const result = await api.deleteCanvasClassSync(fetch, data.class.id, 'harvard', keep);
    const response = api.expandResponse(result);
    if (response.error) {
      editDropdownOpen = false;
      invalidateAll();
      sadToast(response.error.detail || 'An unknown error occurred');
    } else {
      editDropdownOpen = false;
      $loadedCanvasClasses = [];
      selectedClass = '';
      invalidateAll();
      timesAdded++;
      happyToast('Canvas class removed successfully!');
    }
  };

  const removeCanvasConnection = async (keep: boolean) => {
    const result = await api.removeCanvasConnection(fetch, data.class.id, 'harvard', keep);
    const response = api.expandResponse(result);
    if (response.error) {
      editDropdownOpen = false;
      invalidateAll();
      sadToast(response.error.detail || 'An unknown error occurred');
    } else {
      editDropdownOpen = false;
      invalidateAll();
      timesAdded++;
      happyToast('Canvas class connection removed successfully!');
    }
  };

  // The HTMLElement refs of the canvas class options.
  let classNodes: { [key: string]: HTMLElement } = {};
  // Clean up state on navigation. Invalidate data so that any changes
  // are reflected in the rest of the app. (If performance suffers here,
  // we can be more selective about what we invalidate.)
  onNavigate(() => {
    uploads.set([]);
    trashFiles.set([]);
    invalidateAll();
  });

  $: permissions = [
    { name: 'View personal or published assistants', member: true, moderator: true },
    {
      name: 'Create a thread and view personal or published threads',
      member: true,
      moderator: true
    },
    {
      name: 'Create an assistant',
      member: !!data?.class.any_can_create_assistant || false,
      moderator: true
    },
    {
      name: 'Publish an assistant for others to chat with',
      member: !!data?.class.any_can_publish_assistant || false,
      moderator: true
    },
    { name: 'Publish a thread for others to view', member: anyCanPublishThread, moderator: true },
    {
      name: 'View unpublished assistants created by others',
      member: false,
      moderator: !makePrivate
    },
    {
      name: 'View unpublished threads created by others (anonymized)',
      member: false,
      moderator: !makePrivate
    },
    { name: 'Manage group information and user list', member: false, moderator: true }
  ];
</script>

<div
  class="container p-12 space-y-12 divide-y-3 divide-blue-dark-40 dark:divide-gray-700 overflow-y-auto w-full flex flex-col justify-between h-[calc(100%-5rem)]"
>
  <Heading tag="h2" class="text-3xl font-serif font-medium text-blue-dark-40">Manage Group</Heading>
  {#if canEditClassInfo}
    <form on:submit={updateClass} class="pt-4">
      <div class="grid md:grid-cols-3 gap-x-6 gap-y-8">
        <div>
          <Heading customSize="text-xl" tag="h3"
            ><Secondary class="text-3xl text-black font-normal">Group Details</Secondary></Heading
          >
          <Info>General information about the group.</Info>
        </div>
        <div>
          <Label for="name">Name</Label>
          <Input
            label="Name"
            id="name"
            name="name"
            value={data.class.name}
            on:change={submitParentForm}
            disabled={$updatingClass}
          />
        </div>

        <div>
          <Label for="term">Session</Label>
          <Input
            label="Session"
            id="term"
            name="term"
            value={data.class.term}
            on:change={submitParentForm}
            disabled={$updatingClass}
          />
        </div>

        <div></div>
        <Helper
          >Choose whether to make threads and assistants in this group private. When checked, only
          members can view unpublished threads and assistants they create.</Helper
        >
        <div>
          <Checkbox
            id="make_private"
            name="make_private"
            disabled={$updatingClass}
            on:change={submitParentForm}
            bind:checked={makePrivate}>Make threads and assistants private</Checkbox
          >
        </div>

        <div></div>
        <Helper
          >Choose whether to allow members to share their threads with the rest of the group.
          Moderators are always allowed to publish threads.</Helper
        >
        <div>
          <Checkbox
            id="any_can_publish_thread"
            name="any_can_publish_thread"
            disabled={$updatingClass}
            on:change={submitParentForm}
            bind:checked={anyCanPublishThread}>Allow members to publish threads</Checkbox
          >
        </div>

        <div></div>
        <Helper
          >Choose the level of permissions members should have for creating their own assistants and
          sharing them with the group. Moderators will always be able to create and publish
          assistants.</Helper
        >
        <Select
          items={asstPermOptions}
          value={assistantPermissions}
          name="asst_perm"
          on:change={submitParentForm}
          disabled={$updatingClass}
        />

        <div></div>

        <div class="col-span-2">
          <PermissionsTable {permissions} />
        </div>
      </div>
    </form>
  {/if}

  {#if canViewApiKey}
    <form on:submit={submitUpdateApiKey} class="pt-6">
      <div class="grid md:grid-cols-3 gap-x-6 gap-y-8">
        <div>
          <Heading customSize="text-xl font-bold" tag="h3"
            ><Secondary class="text-3xl text-black font-normal">Billing</Secondary></Heading
          >
          <Info>Manage OpenAI credentials</Info>
        </div>

        <div class="col-span-2">
          <Label for="apiKey">API Key</Label>
          <div class="w-full relative pt-2 pb-2" class:cursor-pointer={$blurred}>
            {#if !hasApiKey}
              <ButtonGroup class="w-full">
                <InputAddon>
                  <PenOutline class="w-6 h-6" />
                </InputAddon>
                <Input
                  id="apiKey"
                  name="apiKey"
                  label="API Key"
                  autocomplete="off"
                  value={apiKey}
                  placeholder="Your API key here"
                />
              </ButtonGroup>
            {:else}
              <ButtonGroup class="w-full">
                <InputAddon>
                  <button type="button" on:click={() => ($blurred = !$blurred)}>
                    {#if !$blurred}
                      <EyeOutline class="w-6 h-6" />
                    {:else}
                      <EyeSlashOutline class="w-6 h-6" />
                    {/if}
                  </button>
                </InputAddon>
                <Input
                  id="apiKey"
                  name="apiKey"
                  label="API Key"
                  autocomplete="off"
                  class={$blurred ? 'cursor-pointer' : undefined}
                  value={$blurred ? apiKeyBlur : apiKey}
                  on:focus={() => ($blurred = false)}
                  on:blur={() => ($blurred = true)}
                  readonly
                  placeholder="Your API key here"
                />
              </ButtonGroup>
            {/if}
          </div>

          {#if hasApiKey}
            <Helper
              >Note: Changing the API key will break all threads and assistants in the group, so it
              is not currently supported.</Helper
            >
          {/if}
        </div>

        {#if !hasApiKey}
          <div></div>
          <div></div>
          <div>
            <Button
              pill
              type="submit"
              disabled={$updatingApiKey}
              class="bg-orange text-white hover:bg-orange-dark">Save</Button
            >
          </div>
        {/if}
      </div>
    </form>
  {/if}

  {#if canManageClassUsers}
    <div class="grid md:grid-cols-3 gap-x-6 gap-y-8 pt-6">
      <div>
        <Heading customSize="text-xl font-bold" tag="h3"
          ><Secondary class="text-3xl text-black font-normal">Users</Secondary></Heading
        >
        <Info>Manage users who have access to this group.</Info>
      </div>
      <div class="col-span-2">
        {#if !data.class.lms_status || data.class.lms_status === 'none'}
          <Alert
            color="none"
            class="bg-blue-50 text-blue-900"
            defaultClass="p-4 gap-3 text-sm border-2 border-blue-200"
          >
            <div class="p-1.5">
              <div class="flex flex-row justify-between items-center">
                <div class="flex items-center gap-3">
                  <CanvasLogo size="5" />
                  <span class="text-lg font-medium"
                    >Sync your PingPong group's users with Canvas</span
                  >
                </div>
                <CloseButton class="hover:bg-blue-200" on:click={dismissCanvasSync} />
              </div>
              <p class="mt-2 mb-4 text-sm">
                If you're teaching a course at Harvard, link your PingPong group with your Canvas
                course to automatically sync your course roster with PingPong.
              </p>
              <div class="flex gap-1">
                <Button
                  pill
                  size="xs"
                  class="border border-blue-900 bg-gradient-to-t from-blue-900 to-blue-800 text-white hover:from-blue-800 hover:to-blue-700"
                  on:click={redirectToCanvas}
                  on:touchstart={redirectToCanvas}
                >
                  <LinkOutline class="w-4 h-4 me-2" />Sync with Canvas</Button
                >
              </div>
            </div>
          </Alert>
        {:else if data.class.lms_status === 'authorized' && data.class.lms_user?.id && data.me.user?.id === data.class.lms_user?.id}
          <Alert color="yellow" defaultClass="p-4 gap-3 text-sm border-2">
            <div class="p-1.5">
              <div class="flex items-center gap-3">
                <CanvasLogo size="5" />
                <span class="text-lg font-medium"
                  >Almost there: Select which Canvas class to sync</span
                >
              </div>
              <p class="mt-2 mb-4 text-sm">
                Your Canvas account is now connected to this PingPong group. Select which class
                you'd like to link with this PingPong group.
              </p>
              <div class="flex flex-row gap-2 items-stretch">
                {#if canvasClasses.length > 0}
                  <DropdownContainer
                    optionNodes={classNodes}
                    bind:dropdownOpen={classSelectDropdownOpen}
                    bind:selectedOption={selectedClass}
                    placeholder={selectedClassName}
                    width="w-full"
                  >
                    <CanvasClassDropdownOptions
                      {canvasClasses}
                      {selectedClass}
                      {updateSelectedClass}
                      bind:classNodes
                    />
                  </DropdownContainer>
                  <div class="flex gap-2 items-center">
                    <Button
                      pill
                      size="xs"
                      class="shrink-0 max-h-fit border border-amber-900 bg-gradient-to-t from-amber-900 to-amber-800 text-white hover:from-amber-800 hover:to-amber-700"
                      on:click={saveSelectedClass}
                      on:touchstart={saveSelectedClass}
                      disabled={loadingCanvasClasses || !selectedClass}
                    >
                      Save</Button
                    >
                    <Button
                      pill
                      size="xs"
                      class="shrink-0 max-h-fit border border-gray-400 bg-gradient-to-t from-gray-100 to-gray-100 text-gray-800 hover:from-gray-200 hover:to-gray-100"
                      on:click={() => {
                        $loadedCanvasClasses = [];
                        selectedClass = '';
                      }}
                      on:touchstart={() => {
                        $loadedCanvasClasses = [];
                        selectedClass = '';
                      }}
                    >
                      Cancel</Button
                    >
                  </div>
                {:else}
                  <div class="flex flex-row flex-grow gap-2 justify-between items-center">
                    <Button
                      pill
                      size="xs"
                      class="border border-amber-900 bg-gradient-to-t from-amber-900 to-amber-800 text-white hover:from-amber-800 hover:to-amber-700"
                      on:click={loadCanvasClasses}
                      on:touchstart={loadCanvasClasses}
                    >
                      {#if loadingCanvasClasses}<Spinner
                          color="white"
                          class="w-4 h-4 me-2"
                        />{:else}<LinkOutline class="w-4 h-4 me-2" />{/if}Load your classes</Button
                    >
                    <Button
                      pill
                      size="xs"
                      class="border border-amber-900 hover:bg-amber-900 text-amber-900 hover:bg-gradient-to-t hover:from-amber-800 hover:to-amber-700 hover:text-white"
                      disabled={syncingCanvasClass || $updatingApiKey}
                      on:click={() => removeCanvasConnection(false)}
                      on:touchstart={() => removeCanvasConnection(false)}
                    >
                      <UserRemoveSolid class="w-4 h-4 me-2" />Disconnect Canvas account</Button
                    >
                  </div>
                {/if}
              </div>
            </div>
          </Alert>
        {:else if data.class.lms_status === 'authorized'}
          <Alert color="yellow" defaultClass="p-4 gap-3 text-sm border-2">
            <div class="p-1.5">
              <div class="flex items-center gap-3">
                <CanvasLogo size="5" />
                <span class="text-lg font-medium">Canvas Sync setup in process</span>
              </div>
              <p class="mt-2 text-sm">
                {data.class.lms_user?.name || 'Someone in your course'} has linked their Canvas account
                with this group. Once they have selected a course to sync with this group, PingPong will
                automatically sync the course's roster.
              </p>
              <p class="mt-2 text-sm">
                Need to link your own account? Ask {data.class.lms_user?.name || 'them'} to disconnect
                their Canvas account from this PingPong group.
              </p>
            </div>
          </Alert>
        {:else if data.class.lms_status === 'linked' && data.class.lms_user?.id && data.me.user?.id === data.class.lms_user?.id}
          <Alert color="green" defaultClass="p-4 gap-3 text-sm border-2">
            <div class="p-1.5">
              <div class="flex items-center gap-3">
                <div class="animate-pulse"><CanvasLogo size="5" /></div>
                <span class="text-lg font-medium">Canvas Sync is active</span>
              </div>
              <p class="mt-2 text-sm">
                This PingPong group is linked to <span class="font-semibold"
                  >{canvasLinkedClass?.course_code}: {canvasLinkedClass?.name}</span
                >
                on Canvas. The class roster is automatically synced with this group's user list about
                once every hour. Use the Sync button below to request an immediate sync.
              </p>
              <p class="mt-2 mb-4 text-sm">
                Last sync: {data.class.lms_last_synced
                  ? dayjs.utc(data.class.lms_last_synced).fromNow()
                  : 'never'}
              </p>
              <div class="flex flex-row justify-between items-center">
                <Button
                  pill
                  size="xs"
                  class="border border-green-900 bg-gradient-to-t from-green-800 to-green-700 text-white hover:from-green-700 hover:to-green-600"
                  on:click={syncClass}
                  on:touchstart={syncClass}
                  disabled={syncingCanvasClass || $updatingApiKey}
                >
                  {#if syncingCanvasClass}<Spinner color="white" class="w-4 h-4 me-2" />Syncing
                    roster...{:else}<RefreshOutline class="w-4 h-4 me-2" />Sync roster{/if}</Button
                >
                <Button
                  pill
                  size="xs"
                  class="border border-green-900 hover:bg-green-900 text-green-900 hover:bg-gradient-to-t hover:from-green-800 hover:to-green-700 hover:text-white"
                  disabled={syncingCanvasClass || $updatingApiKey}
                >
                  <AdjustmentsHorizontalOutline class="w-4 h-4 me-2" />Edit Canvas Sync</Button
                >
                <Dropdown bind:open={editDropdownOpen}>
                  <DropdownItem on:click={() => (disconnectClass = true)}
                    ><div class="flex flex-row gap-2 items-center">
                      <div class="border bg-green-800 border-green-800 text-white rounded-full">
                        <SortHorizontalOutline class="w-4 h-4 m-2" />
                      </div>
                      Sync another class
                    </div></DropdownItem
                  >
                  <DropdownItem on:click={() => (disconnectCanvas = true)}
                    ><div class="flex flex-row gap-3 items-center">
                      <div class="border bg-green-800 border-green-800 text-white rounded-full">
                        <UserRemoveSolid class="w-4 h-4 m-2" />
                      </div>
                      Disconnect Canvas account
                    </div></DropdownItem
                  >
                  <Modal bind:open={disconnectCanvas} size="sm" autoclose>
                    <div class="text-center">
                      <ExclamationCircleOutline class="mx-auto mb-4 text-red-600 w-12 h-12" />
                      <h3 class="mb-5 text-xl text-black font-bold">
                        Remove imported users from {data.class.lms_class?.course_code || 'Canvas'}?
                      </h3>
                      <h4 class="mb-5 text-sm text-black font-normal">
                        While Canvas Sync was active, PingPong imported all users in your Canvas
                        roster. If you keep imported users, you can edit their roles or remove their
                        access to this group at any time.
                      </h4>
                      <div class="flex flex-row gap-2 justify-center">
                        <Button
                          pill
                          color="alternative"
                          on:click={() => removeCanvasConnection(true)}>Keep imported users</Button
                        >
                        <Button pill color="red" on:click={() => removeCanvasConnection(false)}
                          >Remove imported users</Button
                        >
                      </div>
                    </div>
                  </Modal>
                  <Modal bind:open={disconnectClass} size="sm" autoclose>
                    <div class="text-center">
                      <ExclamationCircleOutline class="mx-auto mb-4 text-red-600 w-12 h-12" />
                      <h3 class="mb-5 text-xl text-black font-bold">
                        Remove imported users from {data.class.lms_class?.course_code || 'Canvas'}?
                      </h3>
                      <h4 class="mb-5 text-sm text-black font-normal">
                        While Canvas Sync was active, PingPong imported all users in your Canvas
                        roster. If you keep imported users, you can edit their roles or remove their
                        access to this group at any time.
                      </h4>
                      <div class="flex flex-row gap-2 justify-center">
                        <Button pill color="alternative" on:click={() => deleteClassSync(true)}
                          >Keep imported users</Button
                        >
                        <Button pill color="red" on:click={() => deleteClassSync(false)}
                          >Remove imported users</Button
                        >
                      </div>
                    </div>
                  </Modal>
                </Dropdown>
              </div>
            </div>
          </Alert>
        {:else if data.class.lms_status === 'linked'}
          <Alert color="green" defaultClass="p-4 gap-3 text-sm border-2">
            <div class="p-1.5">
              <div class="flex items-center gap-3">
                <div class="animate-pulse"><CanvasLogo size="5" /></div>
                <span class="text-lg font-medium">Canvas Sync is active</span>
              </div>
              <p class="mt-2 text-sm">
                This PingPong group is linked to <span class="font-semibold"
                  >{canvasLinkedClass?.course_code}: {canvasLinkedClass?.name}</span
                > on Canvas. The class roster is automatically synced with this group's user list about
                once every hour.
              </p>
              <p class="mt-2 mb-2 text-sm">
                Last sync: {data.class.lms_last_synced
                  ? dayjs.utc(data.class.lms_last_synced).fromNow()
                  : 'never'}
              </p>
              <p class="mt-2 text-sm">
                {data.class.lms_user?.name || 'Someone in your course'} has linked their Canvas account
                with this group. Need to link your own account? Ask {data.class.lms_user?.name ||
                  'them'} to disconnect their Canvas account from this PingPong group.
              </p>
            </div>
          </Alert>
        {:else if data.class.lms_status === 'error' && data.class.lms_user?.id && data.me.user?.id === data.class.lms_user?.id}
          <Alert color="red" defaultClass="p-4 gap-3 text-sm border-2">
            <div class="p-1.5">
              <div class="flex items-center gap-3">
                <CanvasLogo size="5" />
                <span class="text-lg font-medium">Important: Reconnect your Canvas account</span>
              </div>
              <p class="mt-2 text-sm">
                We faced an issue when trying to connect to your Canvas account. Use the
                reconnection button below to reauthorize Pingpong to access your Canvas account and
                ensure uninterrupted syncing of your class roster.
              </p>
              <p class="mt-2 mb-4 text-sm">
                Last sync: {data.class.lms_last_synced
                  ? dayjs.utc(data.class.lms_last_synced).fromNow()
                  : 'never'}
              </p>
              <div class="flex gap-2">
                <Button
                  pill
                  size="xs"
                  class="border border-red-900 bg-gradient-to-t from-red-800 to-red-700 text-white hover:from-red-700 hover:to-red-600"
                  on:click={redirectToCanvas}
                  on:touchstart={redirectToCanvas}
                >
                  <RefreshOutline class="w-4 h-4 me-2" />Reconnect Canvas account</Button
                >
              </div>
            </div>
          </Alert>
        {:else if data.class.lms_status === 'error'}
          <Alert color="red" defaultClass="p-4 gap-3 text-sm border-2">
            <div class="p-1.5">
              <div class="flex items-center gap-3">
                <CanvasLogo size="5" />
                <span class="text-lg font-medium"
                  >Important: Error connecting to Canvas account</span
                >
              </div>
              <p class="mt-2 text-sm">
                {data.class.lms_user?.name || 'Someone in your course'} has linked their Canvas account
                with this group. However, we faced an issue when trying to connect to their Canvas account.
                Ask {data.class.lms_user?.name || 'them'} to reauthorize Pingpong to access your Canvas
                account through this page and ensure uninterrupted syncing of your class roster.
              </p>
              <p class="mt-2 mb-4 text-sm">
                Last sync: {data.class.lms_last_synced
                  ? dayjs.utc(data.class.lms_last_synced).fromNow()
                  : 'never'}
              </p>
              <p class="mt-2 text-sm">
                Need to link your own account? You can disconnect
                their Canvas account from this PingPong group. <span class="font-medium">This action is irreversible and will delete all imported users from Canvas.</span>
              </p>
              <div class="flex gap-2">
                <Button
                  pill
                  size="xs"
                  class="border border-red-900 bg-gradient-to-t from-red-800 to-red-700 text-white hover:from-red-700 hover:to-red-600"
                  on:click={redirectToCanvas}
                  on:touchstart={redirectToCanvas}
                >
                  <RefreshOutline class="w-4 h-4 me-2" />Remove Canvas account</Button
                >
              </div>
            </div>
          </Alert>
        {/if}
        <div class="mb-4">
          <!-- Update the user view when we finish batch adding users. -->
          <!-- Uses a variable for times users have been bulk added -->
          {#key timesAdded}
            <ViewUsers {fetchUsers} {classId} currentUserId={data.me.user?.id} {currentUserRole} />
          {/key}
        </div>
        <div class="flex flex-row justify-between">
          <Button
            pill
            size="md"
            class="bg-orange text-white hover:bg-orange-dark"
            on:click={() => {
              usersModalOpen = true;
            }}
            on:touchstart={() => {
              usersModalOpen = true;
            }}>Invite new users</Button
          >
          {#if data.class.lms_status === 'dismissed'}
            <Button
              pill
              size="md"
              class="bg-white border border-blue-dark-40 text-blue-dark-40 hover:bg-blue-light-50"
              on:click={enableCanvasSync}
              on:touchstart={enableCanvasSync}
              ><div class="flex flex-row gap-2">
                <CanvasLogo size="5" />Sync with Canvas
              </div></Button
            >
          {/if}
        </div>
        {#if usersModalOpen}
          <Modal bind:open={usersModalOpen} title="Invite new users">
            <BulkAddUsers
              {permissions}
              className={data.class.name}
              isPrivate={makePrivate}
              on:submit={submitCreateUsers}
              on:cancel={() => (usersModalOpen = false)}
              role="student"
            />
          </Modal>
        {/if}
      </div>
    </div>
  {/if}

  {#if canUploadClassFiles}
    <div class="grid md:grid-cols-3 gap-x-6 gap-y-8 pt-6">
      <div>
        <Heading tag="h3" customSize="text-xl font-bold"
          ><Secondary class="text-3xl text-black font-normal">Shared Files</Secondary></Heading
        >
        <Info
          >Upload files for use in assistants. Group files are available to everyone in the group
          with permissions to create an assistant. Files must be under {maxUploadSize}. See the
          <a
            href="https://platform.openai.com/docs/api-reference/files/create"
            rel="noopener noreferrer"
            target="_blank"
            class="underline">OpenAI API docs</a
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
              accept={data.uploadInfo.fileTypes({
                code_interpreter: true,
                file_search: true,
                vision: false
              })}
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
</div>
