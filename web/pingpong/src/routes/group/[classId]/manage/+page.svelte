<script lang="ts">
  import { getContext, onMount } from 'svelte';
  import { writable } from 'svelte/store';
  import type { Readable, Writable } from 'svelte/store';
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
    Tooltip,
    Select,
    InputAddon,
    Alert,
    Spinner,
    CloseButton,
    Dropdown,
    DropdownItem,
    Radio
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
    LinkOutline,
    RefreshOutline,
    ChevronDownOutline,
    ShareAllOutline,
    TrashBinOutline,
    EnvelopeOutline,
    SortHorizontalOutline,
    AdjustmentsHorizontalOutline,
    UserRemoveSolid,
    FileLinesOutline,
    ExclamationCircleOutline,
    LockSolid,
    CheckCircleOutline,
    GlobeOutline,
    EyeSlashOutline,
    ArrowRightOutline,
    RectangleListOutline,
    EnvelopeOpenSolid,
    FileCopyOutline,
    ChevronSortOutline
  } from 'flowbite-svelte-icons';
  import { sadToast, happyToast } from '$lib/toast';
  import { humanSize } from '$lib/size';
  import { afterNavigate, goto, invalidateAll, onNavigate } from '$app/navigation';
  import { browser } from '$app/environment';
  import { submitParentForm } from '$lib/form';
  import { page } from '$app/stores';
  import { loading, loadingMessage } from '$lib/stores/general';
  import DropdownContainer from '$lib/components/DropdownContainer.svelte';
  import CanvasClassDropdownOptions from '$lib/components/CanvasClassDropdownOptions.svelte';
  import PermissionsTable from '$lib/components/PermissionsTable.svelte';
  import CanvasDisconnectModal from '$lib/components/CanvasDisconnectModal.svelte';
  import ConfirmationModal from '$lib/components/ConfirmationModal.svelte';
  import OpenAILogo from '$lib/components/OpenAILogo.svelte';
  import AzureLogo from '$lib/components/AzureLogo.svelte';
  import OpenAiLogo from '$lib/components/OpenAILogo.svelte';
  import DropdownBadge from '$lib/components/DropdownBadge.svelte';
  import CloneClassModal from '$lib/components/CloneClassModal.svelte';

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
    5: 'We were unable to complete the authorization request with Canvas. Please try again.',
    6: 'We were unable to process your Thread Export link. Please generate a new one.',
    7: 'Your Thread Export link has expired. Please generate a new one.',
    8: 'You are not the authorized user to perform this action. Only the user that initiated the Thread Export can download the file.',
    9: 'We were unable to fetch your Thread Export file. Please try again.'
  };

  // Function to get error message from error code
  function getErrorMessage(errorCode: number) {
    return (
      errorMessages[errorCode] || 'An unknown error occurred while trying to sync with Canvas.'
    );
  }

  let summaryElement: HTMLElement;
  let manageContainer: HTMLElement;

  // Get the headerHeight store from context
  const headerHeightStore: Readable<number> = getContext('headerHeightStore');
  let headerHeight: number;
  headerHeightStore.subscribe((value) => {
    headerHeight = value;
  });

  onMount(() => {
    const errorCode = $page.url.searchParams.get('error_code');
    if (errorCode) {
      const errorMessage = getErrorMessage(parseInt(errorCode) || 0);
      sadToast(errorMessage);
    }

    // If URL contains the section 'summary', scroll the manageContainer to the summaryElement
    const waitForHeaderHeight = () => {
      if (headerHeight > 0) {
        manageContainer.scrollTo({
          top: summaryElement.offsetTop - headerHeight,
          behavior: 'smooth'
        });
      } else {
        requestAnimationFrame(waitForHeaderHeight);
      }
    };

    const section = $page.url.searchParams.get('section');
    if (section === 'summary') {
      waitForHeaderHeight();
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
  let deleteModal = false;
  let cloneModal = false;
  let exportThreadsModal = false;
  let customSummaryModal = false;
  let defaultDaysToSummarize = 7;
  let daysToSummarize = defaultDaysToSummarize;
  let usersModalOpen = false;
  let anyCanPublishThread = data?.class.any_can_publish_thread || false;
  let anyCanShareAssistant = data?.class.any_can_share_assistant || false;
  let presignedUrlExpiration = data?.class.download_link_expiration || null;
  let makePrivate = data?.class.private || false;
  let assistantPermissions = formatAssistantPermissions(data?.class);
  const asstPermOptions = [
    { value: 'create:0,publish:0,upload:0', name: 'Do not allow members to create' },
    { value: 'create:1,publish:0,upload:1', name: 'Members can create but not publish' },
    { value: 'create:1,publish:1,upload:1', name: 'Members can create and publish' }
  ];
  let availableInstitutions: api.Institution[] = [];
  let availableTransferInstitutions: api.Institution[] = [];
  let currentInstitutionId: number | null = null;
  $: availableInstitutions = (data?.admin?.canCreateClass || [])
    .slice()
    .sort((a, b) => a.name.localeCompare(b.name));
  $: currentInstitutionId = data?.class?.institution_id ?? null;
  $: availableTransferInstitutions = availableInstitutions.filter(
    (inst) => inst.id !== currentInstitutionId
  );
  let transferModal = false;
  let transferInstitutionId: number | null = null;
  $: {
    if (availableTransferInstitutions.length === 0) {
      transferInstitutionId = null;
    } else if (
      transferInstitutionId === null ||
      !availableTransferInstitutions.some((inst) => inst.id === transferInstitutionId)
    ) {
      transferInstitutionId = availableTransferInstitutions[0].id;
    }
  }
  $: hasCreatePermissionForCurrent =
    currentInstitutionId !== null &&
    availableInstitutions.some((inst) => inst.id === currentInstitutionId);
  $: transferInstitutionOptions = availableTransferInstitutions.map((inst) => ({
    value: inst.id.toString(),
    name: inst.name
  }));
  let transferring = false;
  let anyCanPublishAssistant =
    parseAssistantPermissions(assistantPermissions).any_can_publish_assistant;

  // Check if the group has been rate limited by OpenAI recently
  $: lastRateLimitedAt = data?.class.last_rate_limited_at
    ? dayjs().diff(dayjs(data.class.last_rate_limited_at), 'day') > 7
      ? null
      : dayjs(data.class.last_rate_limited_at).format('MMMM D, YYYY [at] h:mma')
    : null;

  $: apiKey = data.apiKey || null;
  let apiProvider = 'openai';

  $: subscriptionInfo = data.subscription || null;

  let uploads = writable<FileUploadInfo[]>([]);
  const trashFiles = writable<number[]>([]);
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

  $: hasApiKey = !!data?.hasAPIKey;
  $: canExportThreads = !!data?.grants?.isAdmin || !!data?.grants?.isTeacher;
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
  const resetInterface = (e: CustomEvent<CreateClassUsersRequest>) => {
    invalidateAll();
    usersModalOpen = false;
    timesAdded++;
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
      any_can_share_assistant: d.any_can_share_assistant?.toString() === 'on',
      private: makePrivate,
      ...parseAssistantPermissions(d.asst_perm.toString())
    };

    const result = await api.updateClass(fetch, data.class.id, update);
    if (api.isErrorResponse(result)) {
      $updatingClass = false;
      let msg = result.detail || 'An unknown error occurred';
      sadToast(msg);
    } else {
      await invalidateAll();
      anyCanPublishThread = data?.class.any_can_publish_thread || false;
      anyCanShareAssistant = data?.class.any_can_share_assistant || false;
      assistantPermissions = formatAssistantPermissions(data?.class);
      anyCanPublishAssistant =
        parseAssistantPermissions(assistantPermissions).any_can_publish_assistant;
      $updatingClass = false;
      happyToast('Saved group info');
    }
  };

  /**
   * Delete the class.
   */
  const deleteClass = async (evt: CustomEvent) => {
    evt.preventDefault();
    $loadingMessage = 'Deleting group. This may take a while.';
    $loading = true;

    if (!data.class.id) {
      $loadingMessage = '';
      $loading = false;
      sadToast(`Error: Group ID not found.`);
      return;
    }

    const result = await api.deleteClass(fetch, data.class.id);
    if (result.$status >= 300) {
      $loadingMessage = '';
      $loading = false;
      sadToast(`Error deleting group: ${JSON.stringify(result.detail, null, '  ')}`);
      return;
    }

    $loadingMessage = '';
    $loading = false;
    happyToast('Group deleted');
    await goto(`/`, { invalidateAll: true });
    return;
  };

  const cloneClass = async (evt: CustomEvent<api.CopyClassRequestInfo>) => {
    evt.preventDefault();
    cloneModal = false;
    $loading = true;
    const requestInfo = evt.detail;

    if (!data.class.id) {
      $loading = false;
      sadToast(`Error: Group ID not found.`);
      return;
    }

    const copyOptions: api.CopyClassRequest = {
      name: requestInfo.groupName.toString(),
      term: requestInfo.groupSession.toString(),
      institution_id: requestInfo.institutionId ?? currentInstitutionId,
      any_can_publish_thread: requestInfo.anyCanPublishThread,
      any_can_share_assistant: requestInfo.anyCanShareAssistant,
      private: requestInfo.makePrivate,
      copy_assistants: requestInfo.assistantCopy,
      copy_users: requestInfo.userCopy,
      ...parseAssistantPermissions(requestInfo.assistantPermissions)
    };

    const result = await api.copyClass(fetch, data.class.id, copyOptions);
    const response = api.expandResponse(result);
    if (response.error) {
      sadToast(response.error.detail || 'An unknown error occurred');
    } else {
      happyToast(
        "We've started creating your cloned group. You'll receive an email when the new group is ready.",
        5000
      );
    }
    $loading = false;
  };

  const transferClassInstitution = async () => {
    if (!hasCreatePermissionForCurrent) {
      sadToast(
        'You need permission to create classes in the current institution to transfer this group.'
      );
      return;
    }

    if (!transferInstitutionId) {
      sadToast('Select an institution to transfer this group to.');
      return;
    }

    transferring = true;
    const result = await api.transferClass(fetch, data.class.id, {
      institution_id: transferInstitutionId
    });
    const response = api.expandResponse(result);
    if (response.error) {
      sadToast(response.error.detail || 'An unknown error occurred');
    } else {
      const targetInstitutionName =
        availableInstitutions.find((inst) => inst.id === transferInstitutionId)?.name ||
        response.data.institution?.name ||
        'the new institution';
      currentInstitutionId = response.data.institution_id;
      happyToast(`Group transferred to ${targetInstitutionName}.`);
      transferModal = false;
      await invalidateAll();
    }
    transferring = false;
  };

  const handleTransferInstitutionChange = (evt: Event) => {
    const target = evt.target as HTMLSelectElement;
    const selectedValue = parseInt(target.value, 10);
    transferInstitutionId = Number.isNaN(selectedValue) ? null : selectedValue;
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
      sadToast('Please provide an API key.');
      return;
    }

    if (!d.endpoint && d.provider === 'azure') {
      $updatingApiKey = false;
      sadToast('Please provide your Azure deployment endpoint.');
      return;
    }

    const _apiKey = (d.apiKey as string | undefined) || '';
    const _endpoint = d.endpoint as string | undefined;
    const _provider = (d.provider as string | undefined) || 'openai';
    const result = await api.updateApiKey(fetch, data.class.id, _provider, _apiKey, _endpoint);

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
  $: canvasInstances = data.canvasInstances || [];

  const redirectToCanvas = async (tenantId: string) => {
    const result = await api.getCanvasLink(fetch, data.class.id, tenantId);
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
    const result = await api.dismissCanvasSync(fetch, data.class.id);
    const response = api.expandResponse(result);
    if (response.error) {
      sadToast(response.error.detail || 'An unknown error occurred');
    } else {
      invalidateAll();
    }
  };
  const enableCanvasSync = async () => {
    const result = await api.bringBackCanvasSync(fetch, data.class.id);
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
      term: c.term,
      lms_tenant: c.lms_tenant
    }))
    .sort((a, b) => a.course_code.localeCompare(b.course_code));

  // Whether we are currently loading canvas classes from the API.
  let loadingCanvasClasses = false;
  // Load canvas classes from the API.
  const loadCanvasClasses = async () => {
    if (!data.class.lms_tenant) {
      sadToast('No Canvas account linked to this group.');
      return;
    }
    loadingCanvasClasses = true;
    const result = await api.loadCanvasClasses(fetch, data.class.id, data.class.lms_tenant);
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

  const updateSelectedClass = async (classValue: string) => {
    canvasClassVerified = false;
    canvasClassBeingVerified = true;
    canvasClassVerificationError = '';
    classSelectDropdownOpen = false;
    selectedClass = classValue;
    await verifyCanvasClass();
  };

  const saveSelectedClass = async () => {
    if (!selectedClass) {
      return;
    }
    if (!data.class.lms_tenant) {
      sadToast('No Canvas account linked to this group.');
      return;
    }
    const result = await api.saveCanvasClass(
      fetch,
      data.class.id,
      data.class.lms_tenant,
      selectedClass
    );
    const response = api.expandResponse(result);
    if (response.error) {
      sadToast(response.error.detail || 'An unknown error occurred');
    } else {
      invalidateAll();
      happyToast('Canvas class successfully linked!');
    }
  };

  let canvasClassVerified = false;
  let canvasClassBeingVerified = false;
  let canvasClassVerificationError = '';

  const verifyCanvasClass = async () => {
    if (!data.class.lms_tenant) {
      sadToast('No Canvas account linked to this group.');
      return;
    }
    canvasClassBeingVerified = true;
    const result = await api.verifyCanvasClass(
      fetch,
      data.class.id,
      data.class.lms_tenant,
      selectedClass
    );
    const response = api.expandResponse(result);
    if (response.error) {
      canvasClassVerificationError =
        response.error.detail ||
        'There was an issue while trying to verify your access to the class roster. Try again later.';
    } else {
      canvasClassVerified = true;
    }
    canvasClassBeingVerified = false;
  };

  let syncingCanvasClass = false;
  const syncClass = async () => {
    if (!data.class.lms_tenant) {
      sadToast('No Canvas account linked to this group.');
      return;
    }
    syncingCanvasClass = true;
    const result = await api.syncCanvasClass(fetch, data.class.id, data.class.lms_tenant);
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
    if (!data.class.lms_tenant) {
      sadToast('No Canvas account linked to this group.');
      return;
    }
    const result = await api.deleteCanvasClassSync(
      fetch,
      data.class.id,
      data.class.lms_tenant,
      keep
    );
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

  let removingCanvasConnection = false;
  const removeCanvasConnection = async (keep: boolean) => {
    if (!data.class.lms_tenant) {
      sadToast('No Canvas account linked to this group.');
      return;
    }
    removingCanvasConnection = true;
    const result = await api.removeCanvasConnection(
      fetch,
      data.class.id,
      data.class.lms_tenant,
      keep
    );
    const response = api.expandResponse(result);
    if (response.error) {
      editDropdownOpen = false;
      removingCanvasConnection = false;
      invalidateAll();
      sadToast(response.error.detail || 'An unknown error occurred', 5000);
    } else {
      editDropdownOpen = false;
      removingCanvasConnection = false;
      invalidateAll();
      timesAdded++;
      happyToast('Canvas class connection removed successfully!');
    }
  };

  const exportThreads = async () => {
    const result = await api.exportThreads(fetch, data.class.id);
    const response = api.expandResponse(result);
    if (response.error) {
      sadToast(response.error.detail || 'An unknown error occurred');
    } else {
      happyToast("We've started exporting your threads. You'll receive an email when it's ready.");
    }
  };

  const requestSummary = async () => {
    const result = await api.requestActivitySummary(fetch, data.class.id, {
      days: daysToSummarize
    });
    const response = api.expandResponse(result);
    if (response.error) {
      sadToast(response.error.detail || 'An unknown error occurred');
    } else {
      happyToast(
        "We've started creating your Activity Summary. You'll receive an email when it's ready.",
        5000
      );
    }
    daysToSummarize = defaultDaysToSummarize;
  };

  const reconnectCanvasAccount = async () => {
    if (!canvasLinkedClass) {
      sadToast('No Canvas class linked to this group.');
      return;
    }
    const tenant = canvasLinkedClass?.lms_tenant;
    const result = await api.removeCanvasConnection(fetch, data.class.id, tenant, true);
    const response = api.expandResponse(result);
    if (response.error) {
      invalidateAll();
      sadToast(response.error.detail || 'An unknown error occurred');
    } else {
      await redirectToCanvas(tenant);
    }
  };

  const unsubscribeFromSummaries = async () => {
    const result = await api.unsubscribeFromSummary(fetch, data.class.id);
    const response = api.expandResponse(result);
    if (response.error) {
      sadToast(response.error.detail || 'An unknown error occurred');
    } else {
      happyToast(
        "Successfully unsubscribed from Activity Summaries. You won't receive any more emails."
      );
    }
  };

  const subscribeToSummaries = async () => {
    const result = await api.subscribeToSummary(fetch, data.class.id);
    const response = api.expandResponse(result);
    if (response.error) {
      sadToast(response.error.detail || 'An unknown error occurred');
    } else {
      happyToast(
        'Successfully subscribed to Activity Summaries. You will receive an email every week.'
      );
    }
  };

  const handleSubscriptionChange = async (event: Event) => {
    const target = event.target as HTMLInputElement;
    if (target.checked) {
      await subscribeToSummaries();
    } else {
      await unsubscribeFromSummaries();
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
  });
  afterNavigate(() => {
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
    {
      name: 'Create a share link for anyone, including non-PingPong users to chat with',
      member: !!data?.class.any_can_share_assistant || false,
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

  let aboutToSetPrivate: boolean = false;
  let originalEvent: Event;

  function handleClick(event: MouseEvent): void {
    event.preventDefault();
    originalEvent = event;
    aboutToSetPrivate = true;
  }

  function handleMakePrivate(): void {
    if (
      !confirm(
        `You are about to make threads and assistants private in this group. This action CANNOT be undone and you'll have to create a new group to see threads and assistants of other members as a Moderator.\n\nAre you sure you want to continue?`
      )
    ) {
      aboutToSetPrivate = false;
      return;
    }
    makePrivate = true;
    if (originalEvent) {
      submitParentForm(originalEvent);
    }
    aboutToSetPrivate = false;
  }
</script>

<div
  class="container p-12 space-y-12 divide-y-3 divide-blue-dark-40 dark:divide-gray-700 overflow-y-auto w-full flex flex-col justify-between h-[calc(100%-5rem)]"
  bind:this={manageContainer}
>
  <div class="flex flex-row justify-between">
    <Heading tag="h2" class="text-3xl font-serif font-medium text-blue-dark-40"
      >Manage Group</Heading
    >

    <div class="flex items-start shrink-0 gap-1">
      <Button
        pill
        size="sm"
        href="https://docs.google.com/document/d/1W6RtXiNDxlbji7BxmzMGaXT__yyITDmHzczH0d344lY/edit?usp=sharing"
        rel="noopener noreferrer"
        target="_blank"
        class="bg-white border border-blue-dark-40 text-blue-dark-40 hover:text-white hover:bg-blue-dark-40"
        ><div class="flex flex-row justify-between gap-2">
          <FileLinesOutline />
          <div>User Guide</div>
        </div></Button
      >
      <Button
        pill
        size="sm"
        class="bg-white text-blue-dark-40 border-solid border border-blue-dark-40 hover:text-white hover:bg-blue-dark-40"
        >More options <ChevronDownOutline /></Button
      >
      <Dropdown class="overflow-y-auto">
        {#if canExportThreads}
          <DropdownItem
            on:touchstart={() => (exportThreadsModal = true)}
            on:click={() => (exportThreadsModal = true)}
            disabled={makePrivate}
            class="tracking-wide flex flex-row items-center gap-2 text-blue-dark-40 disabled:text-gray-400 disabled:cursor-not-allowed disabled:hover:bg-white"
          >
            <ShareAllOutline />
            <div>Export threads</div>
          </DropdownItem>
          {#if makePrivate}
            <Tooltip defaultClass="text-wrap py-2 px-3 text-sm font-normal shadow-sm" arrow={false}
              >You can't export threads because they are private in this group.</Tooltip
            >
          {/if}
        {/if}
        <DropdownItem
          on:touchstart={() => (cloneModal = true)}
          on:click={() => (cloneModal = true)}
          class="tracking-wide flex flex-row items-center gap-2 text-blue-dark-40"
        >
          <FileCopyOutline />
          <div>Clone group</div>
        </DropdownItem>

        <DropdownItem
          on:touchstart={() => (deleteModal = true)}
          on:click={() => (deleteModal = true)}
          class="tracking-wide flex flex-row items-center gap-2 text-red-700"
        >
          <TrashBinOutline />
          <div>Delete group</div>
        </DropdownItem>
      </Dropdown>
      <Modal bind:open={exportThreadsModal} size="xs" autoclose>
        <div class="text-center px-2">
          <EnvelopeOutline class="mx-auto mb-4 text-slate-500 w-12 h-12" />
          <h3 class="mb-5 text-xl text-gray-900 dark:text-white font-bold">
            Before we start exporting
          </h3>
          <p class="mb-5 text-sm text-gray-700 dark:text-gray-300">
            Depending on the number of threads in your group, exporting may take a while. You'll
            receive an email when your threads are ready to download.
            {#if presignedUrlExpiration}<span class="font-bold"
                >The download link will be valid for {presignedUrlExpiration}.</span
              >{/if}
          </p>
          <div class="flex justify-center gap-4">
            <Button pill color="alternative" on:click={() => (exportThreadsModal = false)}
              >Cancel</Button
            >
            <Button pill outline color="blue" on:click={exportThreads}>Export threads</Button>
          </div>
        </div>
      </Modal>
      <Modal bind:open={deleteModal} size="xs" autoclose>
        <ConfirmationModal
          warningTitle={`Delete ${data?.class.name || 'this group'}?`}
          warningDescription="All assistants, threads and files associated with this group will be deleted."
          warningMessage="This action cannot be undone."
          cancelButtonText="Cancel"
          confirmText="delete"
          confirmButtonText="Delete group"
          on:confirm={deleteClass}
          on:cancel={() => (deleteModal = false)}
        />
      </Modal>
      <Modal bind:open={cloneModal} size="md">
        <CloneClassModal
          groupName={data?.class.name || ''}
          groupSession={data?.class.term || ''}
          institutions={availableInstitutions}
          {currentInstitutionId}
          {makePrivate}
          aiProvider={apiProvider}
          {anyCanPublishThread}
          {assistantPermissions}
          {anyCanShareAssistant}
          on:confirm={cloneClass}
          on:cancel={() => (cloneModal = false)}
        />
      </Modal>
      <Modal bind:open={transferModal} size="md">
        <div class="flex flex-col gap-4 p-1">
          <Heading customSize="text-xl" tag="h3"
            ><Secondary class="text-3xl font-serif font-medium text-blue-dark-40"
              >Transfer group</Secondary
            ></Heading
          >
          <p class="text-sm text-slate-700">
            Move this group to another institution without losing your roster or settings. You can
            only transfer this group to an institution where you have create-group permissions.
          </p>
          <div class="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <div class="text-xs uppercase tracking-wide text-slate-500">Current institution</div>
            <div class="text-base font-semibold text-slate-900">
              {data.class.institution?.name || 'Not linked to an institution'}
            </div>
          </div>
          <div class="space-y-2">
            <Label for="transferInstitution">Transfer to</Label>
            {#if transferInstitutionOptions.length > 0}
              <Select
                id="transferInstitution"
                name="transferInstitution"
                items={transferInstitutionOptions}
                value={transferInstitutionId ? transferInstitutionId.toString() : ''}
                on:change={handleTransferInstitutionChange}
                disabled={transferring}
              />
            {:else}
              <div class="rounded-lg border border-slate-200 bg-white p-3 text-sm text-slate-700">
                No other eligible institutions available for transfer.
              </div>
            {/if}
          </div>
          <div class="flex flex-row justify-end gap-2">
            <Button
              pill
              color="light"
              on:click={() => (transferModal = false)}
              disabled={transferring}>Cancel</Button
            >
            <Button
              type="button"
              pill
              color="blue"
              class="flex items-center gap-2"
              disabled={transferring || !transferInstitutionId || !hasCreatePermissionForCurrent}
              on:click={transferClassInstitution}
            >
              {#if transferring}
                <Spinner size="5" />
                <span>Transferring...</span>
              {:else}
                <span class="flex items-center gap-2">
                  Transfer<ArrowRightOutline class="h-4 w-4" />
                </span>
              {/if}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  </div>
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
            id="term"
            name="term"
            value={data.class.term}
            on:change={submitParentForm}
            disabled={$updatingClass}
          />
        </div>
        <div></div>
        <div>
          <Label class="mb-1">Institution</Label>
          <p class="text-sm">{data.class.institution?.name || 'Not linked to an institution'}</p>
        </div>

        <div class="flex items-end">
          {#if availableTransferInstitutions.length > 0}
            <Button
              type="button"
              pill
              color="light"
              class="flex items-center gap-2 py-1.5 px-3 text-xs"
              on:click={() => (transferModal = true)}
            >
              Transfer to another institution
              <ArrowRightOutline class="h-4 w-4" />
            </Button>
          {/if}
        </div>

        {#if !makePrivate}
          <div></div>
          <Helper
            >Choose whether to make threads and assistants in this group private. When checked,
            unpublished threads and assistants can only be viewed by those who created them.</Helper
          >
          <div>
            <Checkbox
              id="make_private"
              name="make_private"
              disabled={$updatingClass || makePrivate}
              on:click={handleClick}
              bind:checked={makePrivate}
            >
              Make threads and assistants private
            </Checkbox>
            <Modal bind:open={aboutToSetPrivate} size="sm" autoclose>
              <ConfirmationModal
                warningTitle="Are you sure you want to make threads and assistants private?"
                warningDescription="If you turn this setting on, only members can view unpublished threads and assistants they create."
                warningMessage="This action cannot be undone."
                cancelButtonText="Cancel"
                confirmText="confirm"
                confirmButtonText="Make private"
                on:confirm={handleMakePrivate}
                on:cancel={() => (aboutToSetPrivate = false)}
              />
            </Modal>
          </div>
        {/if}

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
        <Helper
          >Choose whether to allow members to create shared links, allowing anyone, even without a
          PingPong account to interact with a published assistant. Moderators will always be able to
          create Shared Links for published assistants.</Helper
        >
        <Checkbox
          id="any_can_share_assistant"
          name="any_can_share_assistant"
          disabled={$updatingClass || !anyCanPublishAssistant}
          on:change={submitParentForm}
          bind:checked={anyCanShareAssistant}
          class={$updatingClass || !anyCanPublishAssistant
            ? 'text-gray-400'
            : '!text-gray-900 !opacity-100'}
        >
          Allow members to create public share links for assistants
        </Checkbox>
        <div></div>

        <div class="col-span-2 flex flex-col gap-3">
          {#if makePrivate}
            <div
              class="flex col-span-2 items-center rounded-lg text-sm text-white bg-gradient-to-r from-gray-800 to-gray-600 border-gradient-to-r from-gray-800 to-gray-600 px-4 py-3"
            >
              <LockSolid class="w-8 h-8 mr-3" />
              <span>
                Unpublished threads and assistants are private in your group. <span
                  class="font-semibold">This setting cannot be changed.</span
                >
              </span>
            </div>
          {/if}
          <PermissionsTable {permissions} />
        </div>
      </div>
    </form>
  {/if}

  {#if subscriptionInfo && hasApiKey}
    <div bind:this={summaryElement} class="grid md:grid-cols-3 gap-x-6 gap-y-8 pt-6">
      <div>
        <Heading customSize="text-xl font-bold" tag="h3"
          ><Secondary class="text-3xl text-black font-normal">Activity Summaries</Secondary
          ></Heading
        >
        <div class="flex flex-col gap-2">
          <Info>Manage your subscription to this group's Activity Summaries.</Info>
          <a
            href="/profile"
            class="text-xs text-gray-600 shrink-0 flex flex-row gap-1 items-center justify-center font-light bg-white rounded-full p-1 px-3 hover:text-blue-dark-100 hover:bg-blue-dark-40 hover:text-white transition-all max-w-max border border-gray-400 hover:border-blue-dark-40"
            >Manage All Subscriptions <ArrowRightOutline size="md" class="inline-block" /></a
          >
        </div>
      </div>
      <div class="flex flex-col col-span-2 gap-5">
        {#if makePrivate}
          <div
            class="flex col-span-2 items-center rounded-lg text-sm text-white bg-gradient-to-r from-gray-800 to-gray-600 border-gradient-to-r from-gray-800 to-gray-600 px-4 py-2"
          >
            <EyeSlashOutline class="w-8 h-8 mr-3" strokeWidth="1" />
            <span> Activity Summaries are unavailable for private groups. </span>
          </div>
        {/if}
        <div class="flex flex-col gap-2">
          <div class="flex flex-row items-end justify-between flex-wrap gap-y-2">
            <div class="flex flex-row gap-2 items-center shrink-0">
              <DropdownBadge
                extraClasses={makePrivate
                  ? 'border-gray-400 from-gray-50 to-gray-100 text-gray-400 items-center'
                  : 'border-blue-400 from-blue-50 to-blue-100 text-blue-700 items-center'}
              >
                <span slot="name">New</span>
              </DropdownBadge>
              <Label for="subscribe" color={makePrivate ? 'disabled' : 'gray'}>
                Sign up for Activity Summaries
              </Label>
            </div>
            {#if !makePrivate}
              <Button
                pill
                size="sm"
                class="text-xs border-blue-dark-40 text-blue-dark-40 shrink-0 flex flex-row gap-1.5 items-center justify-center bg-white rounded-full p-1 px-3 hover:text-blue-dark-100 hover:bg-blue-dark-40 hover:text-white transition-all max-w-max border"
                on:touchstart={() => (customSummaryModal = true)}
                on:click={() => (customSummaryModal = true)}
              >
                <RectangleListOutline />
                <div>Request an Activity Summary</div>
              </Button>
            {/if}
            <Modal bind:open={customSummaryModal} size="xs" autoclose>
              <div class="flex flex-col text-center px-2 gap-4 items-center">
                <EnvelopeOpenSolid class="mx-auto text-slate-500 w-12 h-12" />
                <h3 class="text-xl text-gray-900 dark:text-white font-bold">
                  Let's set up your Activity Summary
                </h3>
                <p class="text-sm text-gray-700 dark:text-gray-300">
                  Select the number of days you'd like to summarize. Depending on the number of
                  threads in your group, creating an Activity Summary may take a while. You'll
                  receive an email with your Activity Summary.
                </p>
                <div class="flex flex-col gap-1 w-full items-center">
                  <Label for="days">Number of days to summarize</Label>
                  <Input
                    type="number"
                    id="days"
                    bind:value={daysToSummarize}
                    name="days"
                    placeholder="7"
                    class="w-1/3"
                  />
                </div>
                <div class="flex justify-center gap-4">
                  <Button pill color="alternative" on:click={() => (customSummaryModal = false)}
                    >Cancel</Button
                  >
                  <Button pill outline color="blue" on:click={requestSummary}
                    >Request Summary</Button
                  >
                </div>
              </div>
            </Modal>
          </div>
          <Helper color={makePrivate ? 'disabled' : 'gray'}
            >PingPong will gather all thread activity in your group and send an AI-generated summary
            with relevant thread links to all Moderators at the end of each week. You can change
            your selection at any time.
          </Helper>
          <Checkbox
            id="subscribe"
            color="blue"
            class={makePrivate ? 'text-gray-400' : ''}
            checked={data.subscription?.subscribed && !makePrivate}
            disabled={makePrivate}
            on:change={handleSubscriptionChange}>Send me weekly Activity Summaries</Checkbox
          >
        </div>
      </div>
    </div>
  {/if}
  {#if canViewApiKey || lastRateLimitedAt}
    <div class="grid md:grid-cols-3 gap-x-6 gap-y-8 pt-6">
      <div>
        <Heading customSize="text-xl font-bold" tag="h3"
          ><Secondary class="text-3xl text-black font-normal">Billing</Secondary></Heading
        >
        <Info>Information about your group's credentials.</Info>
      </div>
      {#if canViewApiKey}
        <div class="col-span-2">
          {#if !hasApiKey}
            <form on:submit={submitUpdateApiKey}>
              <Label for="provider">Choose your AI provider:</Label>
              <Helper class="mb-3"
                >Choose the AI provider you'd like to use for your group. You'll need an API key and
                potentially additional details to set up the connection. <b
                  >You can't change your selection later.</b
                ></Helper
              >
              <div class="grid gap-4 w-full xl:w-2/3 md:grid-cols-2 mb-5">
                <Radio
                  name="provider"
                  value="openai"
                  bind:group={apiProvider}
                  custom
                  class="hidden-radio"
                >
                  <div
                    class="inline-flex gap-4 items-center px-5 py-3 w-full text-gray-900 bg-white rounded-lg border border-gray-200 cursor-pointer peer-checked:border-red-600 peer-checked:text-red-600 hover:text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:bg-gray-800 dark:hover:bg-gray-700 font-normal peer-checked:font-medium min-w-fit"
                  >
                    <OpenAiLogo size="8" extraClass="shrink-0" />
                    <div class="w-full text-base">OpenAI</div>
                  </div>
                </Radio>
                <Radio
                  name="provider"
                  value="azure"
                  bind:group={apiProvider}
                  custom
                  class="hidden-radio"
                >
                  <div
                    class="inline-flex gap-4 items-center px-5 py-3 w-full text-gray-900 bg-white rounded-lg border border-gray-200 cursor-pointer peer-checked:border-red-600 peer-checked:text-red-600 hover:text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:bg-gray-800 dark:hover:bg-gray-700 font-normal peer-checked:font-medium"
                  >
                    <AzureLogo size="8" />
                    <div class="w-full text-base">Azure</div>
                  </div>
                </Radio>
              </div>
              {#if apiProvider == 'azure'}
                <Label for="endpoint">Deployment Endpoint</Label>
                <div class="w-full relative pt-2 pb-2 mb-4">
                  <ButtonGroup class="w-full">
                    <InputAddon>
                      <GlobeOutline class="w-6 h-6" />
                    </InputAddon>
                    <Input
                      id="endpoint"
                      name="endpoint"
                      autocomplete="off"
                      value={apiKey}
                      placeholder="Your deployment endpoint here"
                      defaultClass="block w-full disabled:cursor-not-allowed disabled:opacity-50 rtl:text-right"
                    />
                  </ButtonGroup>
                </div>
              {/if}
              <Label for="apiKey">API Key</Label>
              <div class="w-full relative pt-2 pb-2">
                <ButtonGroup class="w-full">
                  <InputAddon>
                    <PenOutline class="w-6 h-6" />
                  </InputAddon>
                  <Input
                    id="apiKey"
                    name="apiKey"
                    autocomplete="off"
                    value={apiKey}
                    placeholder="Your API key here"
                    defaultClass="block w-full disabled:cursor-not-allowed disabled:opacity-50 rtl:text-right font-mono"
                  />
                </ButtonGroup>
              </div>
              <div class="flex flex-row justify-center">
                <Button
                  pill
                  type="submit"
                  disabled={$updatingApiKey}
                  class="bg-orange text-white hover:bg-orange-dark mt-5">Save</Button
                >
              </div>
            </form>
          {:else}
            <Label for="provider" class="text-sm mb-1">Provider</Label>
            <div class="flex flex-row items-center gap-1.5 mb-5" id="provider">
              {#if apiKey?.provider == 'openai'}
                <OpenAILogo size="5" />
                <span class="text-sm font-normal">OpenAI</span>
              {:else if apiKey?.provider == 'azure'}
                <AzureLogo size="5" />
                <span class="text-sm font-normal">Azure</span>
              {:else if apiKey?.provider}
                <span class="text-sm font-normal">{apiKey?.provider}</span>
              {:else}
                <span class="text-sm font-normal">Unknown</span>
              {/if}
            </div>
            {#if apiKey?.provider == 'azure'}
              <Label for="deploymentEndpoint" class="text-sm">Deployment Endpoint</Label>
              <div class="w-full relative mb-4">
                <span id="deploymentEndpoint" class="text-sm font-normal font-mono"
                  >{apiKey?.endpoint || 'Unknown endpoint'}</span
                >
              </div>
            {/if}
            <Label for="apiKey" class="text-sm">API Key</Label>
            <div class="w-full relative mb-1">
              <span id="apiKey" class="text-sm font-normal font-mono">{apiKey?.api_key}</span>
            </div>
            {#if apiKey?.provider == 'openai'}
              <Helper
                >All your group's assistants, threads, and associated files are tied to your group's
                OpenAI API key, so it can't be changed.</Helper
              >
            {:else if apiKey?.provider == 'azure'}
              <Helper>Changing your Azure API key is not currently supported.</Helper>
            {:else}
              <Helper>Your group's API key can't be changed</Helper>
            {/if}
          {/if}
        </div>
      {/if}

      {#if lastRateLimitedAt}
        {#if canViewApiKey}
          <div></div>
        {/if}
        <div class="col-span-2">
          <Alert color="red" defaultClass="p-4 gap-3 text-sm border-2">
            <div class="p-1.5">
              <div class="flex items-center gap-3">
                <ExclamationCircleOutline class="w-6 h-6" />
                <span class="text-lg font-medium"
                  >Important: Your group has reached OpenAI's request limit</span
                >
              </div>
              <p class="mt-2 mb-4 text-md">
                Your group has recently made more requests to OpenAI than allowed, which means
                you've hit the maximum request limit for now. While you can continue using this
                group, you might have trouble starting new threads or continuing existing
                conversations.
              </p>
              <p class="mt-2 mb-4 text-sm">
                The last time this limit was reached was on <span class="font-medium"
                  >{lastRateLimitedAt}</span
                >. This warning will disappear after 7 days.
              </p>
              <p class="mt-2 text-sm">
                To fix this, try making fewer requests, or if you need more, talk to your group
                administrator about increasing your limit.
              </p>
            </div>
          </Alert>
        </div>
      {/if}
    </div>
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
        {#if canvasInstances.length > 0}
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
                  If you're teaching a course at a supported institution, link your PingPong group
                  with your Canvas course to automatically sync your course roster with PingPong.
                </p>
                <div class="flex gap-1">
                  <Button
                    pill
                    size="xs"
                    class="border border-blue-900 bg-gradient-to-t from-blue-900 to-blue-800 text-white hover:from-blue-800 hover:to-blue-700"
                  >
                    Pick your institution...<ChevronSortOutline class="w-4 h-4 ms-2" /></Button
                  >
                  <Dropdown placement="bottom-start">
                    {#each canvasInstances as instance}
                      <DropdownItem
                        on:click={() => redirectToCanvas(instance.tenant)}
                        class="tracking-wide flex flex-col gap-1"
                      >
                        <span>{instance.tenant_friendly_name}</span>
                        <span class="font-light text-gray-700 text-xs"
                          >{instance.base_url.replace(/^https?:\/\//, '').replace(/\/$/, '')}</span
                        >
                      </DropdownItem>
                    {/each}
                  </Dropdown>
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
                      {#if canvasClassBeingVerified}
                        <Spinner color="yellow" class="w-6 h-6" />
                        <Tooltip
                          defaultClass="text-wrap py-2 px-3 mr-5 text-sm font-light shadow-sm"
                          arrow={false}
                          >We're verifying your access to the class roster. This shouldn't take
                          long.</Tooltip
                        >
                      {:else if canvasClassVerified}
                        <CheckCircleOutline class="w-6 h-6 text-amber-800" />
                        <Tooltip
                          defaultClass="text-wrap py-2 px-3 mr-5 text-sm font-light shadow-sm"
                          arrow={false}>Your access to the class roster has been verified.</Tooltip
                        >
                      {:else if canvasClassVerificationError}
                        <ExclamationCircleOutline class="w-6 h-6 text-amber-800" />
                        <Tooltip
                          defaultClass="text-wrap py-2 px-3 mr-5 text-sm font-light shadow-sm"
                          arrow={false}>{canvasClassVerificationError}</Tooltip
                        >
                      {:else if !canvasClassVerified}
                        <CheckCircleOutline class="w-6 h-6 text-amber-800 text-opacity-25" />
                        <Tooltip
                          defaultClass="text-wrap py-2 px-3 mr-5 text-sm font-light shadow-sm"
                          arrow={false}
                          >We'll verify your permissions to access the class roster. Select a class
                          to begin.</Tooltip
                        >
                      {/if}
                      <Button
                        pill
                        size="xs"
                        class="shrink-0 max-h-fit border border-amber-900 bg-gradient-to-t from-amber-900 to-amber-800 text-white hover:from-amber-800 hover:to-amber-700"
                        on:click={saveSelectedClass}
                        on:touchstart={saveSelectedClass}
                        disabled={loadingCanvasClasses ||
                          !selectedClass ||
                          canvasClassBeingVerified ||
                          !canvasClassVerified}
                      >
                        Save</Button
                      >
                      <Button
                        pill
                        size="xs"
                        class="shrink-0 max-h-fit border border-gray-400 bg-gradient-to-t from-gray-100 to-gray-100 text-gray-800 hover:from-gray-200 hover:to-gray-100"
                        disabled={loadingCanvasClasses || canvasClassBeingVerified}
                        on:click={() => {
                          $loadedCanvasClasses = [];
                          selectedClass = '';
                          canvasClassVerified = false;
                          canvasClassBeingVerified = false;
                          canvasClassVerificationError = '';
                          classSelectDropdownOpen = false;
                        }}
                        on:touchstart={() => {
                          $loadedCanvasClasses = [];
                          selectedClass = '';
                          canvasClassVerified = false;
                          canvasClassBeingVerified = false;
                          canvasClassVerificationError = '';
                          classSelectDropdownOpen = false;
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
                        disabled={removingCanvasConnection || syncingCanvasClass || $updatingApiKey}
                        on:click={() => removeCanvasConnection(false)}
                        on:touchstart={() => removeCanvasConnection(false)}
                      >
                        {#if removingCanvasConnection}<Spinner
                            color="custom"
                            customColor="fill-amber-900"
                            class="w-4 h-4 me-2"
                          />{:else}<UserRemoveSolid class="w-4 h-4 me-2" />{/if}Disconnect Canvas
                        account</Button
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
                  with this group. Once they have selected a course to sync with this group, PingPong
                  will automatically sync the course's roster.
                </p>
                <p class="mt-2 mb-4 text-sm">
                  Need to link your own account? You can disconnect their Canvas account from this
                  PingPong group.
                </p>
                <div class="flex gap-2">
                  <Button
                    pill
                    size="xs"
                    class="border border-amber-900 hover:bg-amber-900 text-amber-900 hover:bg-gradient-to-t hover:from-amber-800 hover:to-amber-700 hover:text-white"
                    disabled={removingCanvasConnection}
                    on:click={() => removeCanvasConnection(false)}
                    on:touchstart={() => removeCanvasConnection(false)}
                  >
                    {#if removingCanvasConnection}<Spinner
                        color="custom"
                        customColor="fill-amber-900"
                        class="w-4 h-4 me-2"
                      />{:else}<UserRemoveSolid class="w-4 h-4 me-2" />{/if}Disconnect Canvas
                    account</Button
                  >
                </div>
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
                  once every hour. Use the Sync button below to request an immediate sync. Users are not
                  notified when they get added to this group though Canvas Sync.
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
                        <div
                          class="border bg-green-800 border-green-800 text-white rounded-full w-8 h-8 flex items-center justify-center"
                        >
                          <SortHorizontalOutline class="w-4 h-4 m-2" />
                        </div>
                        Sync another class
                      </div></DropdownItem
                    >
                    <DropdownItem on:click={() => (disconnectCanvas = true)}
                      ><div class="flex flex-row gap-2 items-center">
                        {#if removingCanvasConnection}<div
                            class="w-8 h-8 flex items-center justify-center"
                          >
                            <Spinner color="custom" customColor="fill-green-800" class="w-5 h-5" />
                          </div>{:else}<div
                            class="border bg-green-800 border-green-800 text-white rounded-full w-8 h-8 flex items-center justify-center"
                          >
                            <UserRemoveSolid class="w-4 h-4 ms-1" />
                          </div>{/if}
                        Disconnect Canvas account
                      </div></DropdownItem
                    >
                    <Modal bind:open={disconnectCanvas} size="sm" autoclose>
                      <CanvasDisconnectModal
                        canvasCourseCode={data.class.lms_class?.course_code || ''}
                        on:keep={() => removeCanvasConnection(true)}
                        on:remove={() => removeCanvasConnection(false)}
                      />
                    </Modal>
                    <Modal bind:open={disconnectClass} size="sm" autoclose>
                      <CanvasDisconnectModal
                        canvasCourseCode={data.class.lms_class?.course_code || ''}
                        on:keep={() => deleteClassSync(true)}
                        on:remove={() => deleteClassSync(false)}
                      />
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
                <p class="mt-2 mb-4 text-sm">
                  {data.class.lms_user?.name || 'Someone in your course'} has linked their Canvas account
                  with this group. Need to link your own account? You can disconnect their Canvas account
                  from this PingPong group.
                  <span class="font-bold"
                    >This action is irreversible and will delete all imported users from Canvas.</span
                  >
                </p>
                <div class="flex gap-2">
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
                    disabled={removingCanvasConnection}
                    on:click={() => (disconnectCanvas = true)}
                    on:touchstart={() => (disconnectCanvas = true)}
                  >
                    {#if removingCanvasConnection}<Spinner
                        color="custom"
                        customColor="fill-green-900"
                        class="w-4 h-4 me-2"
                      />{:else}<UserRemoveSolid class="w-4 h-4 me-2" />{/if}Disconnect Canvas
                    account</Button
                  >
                </div>
                <Modal bind:open={disconnectCanvas} size="sm" autoclose>
                  <CanvasDisconnectModal
                    canvasCourseCode={data.class.lms_class?.course_code || ''}
                    on:keep={() => removeCanvasConnection(true)}
                    on:remove={() => removeCanvasConnection(false)}
                  />
                </Modal>
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
                  We faced an issue when trying to get the class roster from your Canvas account.
                  Use the reconnection button below to reauthorize Pingpong to access your Canvas
                  account and ensure uninterrupted syncing of your class roster.
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
                    class="border border-red-900 bg-gradient-to-t from-red-800 to-red-700 text-white hover:from-red-700 hover:to-red-600"
                    disabled={removingCanvasConnection}
                    on:click={reconnectCanvasAccount}
                    on:touchstart={reconnectCanvasAccount}
                  >
                    <RefreshOutline class="w-4 h-4 me-2" />Reconnect Canvas account</Button
                  >
                  <Button
                    pill
                    size="xs"
                    class="border border-red-900 hover:bg-red-900 text-red-900 hover:bg-gradient-to-t hover:from-red-800 hover:to-red-700 hover:text-white"
                    disabled={removingCanvasConnection}
                    on:click={() => (disconnectCanvas = true)}
                    on:touchstart={() => (disconnectCanvas = true)}
                  >
                    {#if removingCanvasConnection}<Spinner
                        color="custom"
                        customColor="fill-red-900"
                        class="w-4 h-4 me-2"
                      />{:else}<UserRemoveSolid class="w-4 h-4 me-2" />{/if}Disconnect Canvas
                    account</Button
                  >
                </div>
                <Modal bind:open={disconnectCanvas} size="sm" autoclose>
                  <CanvasDisconnectModal
                    canvasCourseCode={data.class.lms_class?.course_code || ''}
                    on:keep={() => removeCanvasConnection(true)}
                    on:remove={() => removeCanvasConnection(false)}
                  />
                </Modal>
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
                <p class="mt-2 mb-4 text-sm">
                  {data.class.lms_user?.name || 'Someone in your course'} has linked their Canvas account
                  with this group. Need to link your own account? You can disconnect their Canvas account
                  from this PingPong group.
                  <span class="font-bold"
                    >This action is irreversible and will delete all imported users from Canvas.</span
                  >
                </p>
                <div class="flex gap-2">
                  <Button
                    pill
                    size="xs"
                    class="border border-green-900 hover:bg-green-900 text-green-900 hover:bg-gradient-to-t hover:from-green-800 hover:to-green-700 hover:text-white"
                    disabled={removingCanvasConnection}
                    on:click={() => (disconnectCanvas = true)}
                    on:touchstart={() => (disconnectCanvas = true)}
                  >
                    {#if removingCanvasConnection}<Spinner
                        color="custom"
                        customColor="fill-green-900"
                        class="w-4 h-4 me-2"
                      />{:else}<UserRemoveSolid class="w-4 h-4 me-2" />{/if}Disconnect Canvas
                    account</Button
                  >
                </div>
                <Modal bind:open={disconnectCanvas} size="sm" autoclose>
                  <CanvasDisconnectModal
                    canvasCourseCode={data.class.lms_class?.course_code || ''}
                    on:keep={() => removeCanvasConnection(true)}
                    on:remove={() => removeCanvasConnection(false)}
                  />
                </Modal>
              </div>
            </Alert>
          {/if}
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
          <Modal bind:open={usersModalOpen} title="Invite new users" dismissable={false}>
            <BulkAddUsers
              {permissions}
              className={data.class.name}
              classId={data.class.id}
              isPrivate={makePrivate}
              on:cancel={() => (usersModalOpen = false)}
              on:close={resetInterface}
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
