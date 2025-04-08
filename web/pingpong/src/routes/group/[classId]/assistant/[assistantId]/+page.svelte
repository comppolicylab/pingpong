<script lang="ts">
  import {
    Helper,
    Button,
    Checkbox,
    Label,
    Input,
    Heading,
    Textarea,
    Modal,
    type SelectOptionType,
    Badge,
    Accordion,
    AccordionItem,
    Range,
    ButtonGroup,
    RadioButton
  } from 'flowbite-svelte';
  import type { Tool, ServerFile, FileUploadInfo } from '$lib/api';
  import { beforeNavigate, goto } from '$app/navigation';
  import * as api from '$lib/api';
  import { setsEqual } from '$lib/set';
  import { happyToast, sadToast } from '$lib/toast';
  import { normalizeNewlines } from '$lib/content.js';
  import {
    CloseOutline,
    ImageOutline,
    QuestionCircleSolid,
    ArrowUpRightFromSquareOutline,
    CogOutline,
    LockSolid,
    BanOutline,
    FileImageOutline,
    ArrowLeftOutline,
    ArrowRightOutline,
    HeartSolid,
    LightbulbSolid,
    MessageDotsSolid,
    MessageDotsOutline,
    MicrophoneOutline,
    MicrophoneSolid
  } from 'flowbite-svelte-icons';
  import MultiSelectWithUpload from '$lib/components/MultiSelectWithUpload.svelte';
  import { writable, type Writable } from 'svelte/store';
  import { loading, loadingMessage } from '$lib/stores/general';
  import ModelDropdownOptions from '$lib/components/ModelDropdownOptions.svelte';
  import DropdownContainer from '$lib/components/DropdownContainer.svelte';
  import DropdownHeader from '$lib/components/DropdownHeader.svelte';
  import DropdownFooter from '$lib/components/DropdownFooter.svelte';
  import ConfirmationModal from '$lib/components/ConfirmationModal.svelte';
  import DropdownBadge from '$lib/components/DropdownBadge.svelte';
  export let data;

  // Flag indicating whether we should check for changes before navigating away.
  let checkForChanges = true;
  let assistantForm: HTMLFormElement;
  let deleteModal = false;
  $: assistant = data.assistant;
  $: preventEdits = !!assistant?.locked;
  $: canPublish = data.grants.canPublishAssistants;

  let interactionMode: 'chat' | 'live_audio';
  $: if (
    assistant?.interaction_mode !== undefined &&
    assistant?.interaction_mode !== null &&
    interactionMode === undefined
  ) {
    interactionMode = assistant.interaction_mode;
  }
  $: if (
    interactionMode === undefined &&
    (data.isCreating ||
      assistant?.interaction_mode === undefined ||
      assistant?.interaction_mode === null)
  ) {
    interactionMode = 'chat';
  }

  let selectedFileSearchFiles = writable(
    data.selectedFileSearchFiles.slice().map((f) => f.file_id)
  );
  let selectedCodeInterpreterFiles = writable(
    data.selectedCodeInterpreterFiles.slice().map((f) => f.file_id)
  );

  // The list of adhoc files being uploaded.
  let privateUploadFSFileInfo = writable<FileUploadInfo[]>([]);
  let privateUploadCIFileInfo = writable<FileUploadInfo[]>([]);
  const trashPrivateFileIds = writable<number[]>([]);
  $: uploadingFSPrivate = $privateUploadFSFileInfo.some((f) => f.state === 'pending');
  $: uploadingCIPrivate = $privateUploadCIFileInfo.some((f) => f.state === 'pending');
  $: privateFSSessionFiles = $privateUploadFSFileInfo
    .filter((f) => f.state === 'success')
    .map((f) => f.response as ServerFile);
  $: privateCISessionFiles = $privateUploadCIFileInfo
    .filter((f) => f.state === 'success')
    .map((f) => f.response as ServerFile);
  $: allFSPrivateFiles = [
    ...data.selectedFileSearchFiles.slice().filter((f) => f.private),
    ...privateFSSessionFiles
  ];
  $: allCIPrivateFiles = [
    ...data.selectedCodeInterpreterFiles.slice().filter((f) => f.private),
    ...privateCISessionFiles
  ];

  const fileSearchMetadata = {
    value: 'file_search',
    name: 'File Search',
    description:
      'File Search augments the Assistant with knowledge from outside its model using documents you provide.',
    max_count: 100
  };
  const codeInterpreterMetadata = {
    value: 'code_interpreter',
    name: 'Code Interpreter',
    description:
      'Code Interpreter can process files with diverse data and formatting, and generate files with data and images of graphs. Code Interpreter allows your Assistant to run code iteratively to solve challenging code and math problems.',
    max_count: 20
  };
  const defaultTools = [{ type: 'file_search' }];

  $: initialTools = (assistant?.tools ? (JSON.parse(assistant.tools) as Tool[]) : defaultTools).map(
    (t) => t.type
  );
  $: modelNameDict = data.models.reduce<{ [key: string]: string }>((acc, model) => {
    acc[model.id] = model.name + (model.is_latest ? ' (Latest)' : ' (Pinned Version)');
    return acc;
  }, {});
  $: latestModelOptions = (
    data.models.filter(
      (model) =>
        model.is_latest &&
        !(model.hide_in_model_selector ?? false) &&
        model.type === interactionMode
    ) || []
  ).map((model) => ({
    value: model.id,
    name: model.name,
    description: model.description,
    supports_vision:
      model.supports_vision &&
      (model.vision_support_override === undefined || model.vision_support_override),
    is_new: model.is_new,
    highlight: model.highlight
  }));
  $: hiddenModelNames = (
    data.models.filter(
      (model) => (model.hide_in_model_selector ?? false) && model.type === interactionMode
    ) || []
  ).map((model) => model.id);
  let selectedModel = '';
  $: if (
    (latestModelOptions.length > 0 && !selectedModel) ||
    !latestModelOptions.map((m) => m.value).includes(selectedModel)
  ) {
    if (
      latestModelOptions.map((m) => m.value).includes(assistant?.model || '') ||
      hiddenModelNames.includes(assistant?.model || '')
    ) {
      selectedModel = assistant?.model || latestModelOptions[0].value;
    } else {
      selectedModel = latestModelOptions[0].value;
    }
  }
  $: selectedModelName = modelNameDict[selectedModel];
  $: versionedModelOptions = (
    data.models.filter(
      (model) =>
        !model.is_latest &&
        !(model.hide_in_model_selector ?? false) &&
        model.type === interactionMode
    ) || []
  ).map((model) => ({
    value: model.id,
    name: model.name,
    description: model.description,
    supports_vision:
      model.supports_vision &&
      (model.vision_support_override === undefined || model.vision_support_override),
    is_new: model.is_new,
    highlight: model.highlight
  }));
  $: supportVisionModels = (data.models.filter((model) => model.supports_vision) || []).map(
    (model) => model.id
  );
  $: supportFileSearchModels = (
    data.models.filter((model) => model.supports_file_search) || []
  ).map((model) => model.id);
  $: supportsFileSearch = supportFileSearchModels.includes(selectedModel);
  $: supportCodeInterpreterModels = (
    data.models.filter((model) => model.supports_code_interpreter) || []
  ).map((model) => model.id);
  $: supportsCodeInterpreter = supportCodeInterpreterModels.includes(selectedModel);
  $: supportTemperatureModels = (
    data.models.filter((model) => model.supports_temperature) || []
  ).map((model) => model.id);
  $: supportsTemperature = supportTemperatureModels.includes(selectedModel);
  $: supportReasoningModels = (data.models.filter((model) => model.supports_reasoning) || []).map(
    (model) => model.id
  );
  $: supportsReasoning = supportReasoningModels.includes(selectedModel);
  $: supportsVision = supportVisionModels.includes(selectedModel);
  $: visionSupportOverride = data.models.find(
    (model) => model.id === selectedModel
  )?.vision_support_override;
  $: finalVisionSupport = visionSupportOverride ?? supportsVision;
  $: allowVisionUpload = true;
  $: asstFSFiles = [...data.files, ...allFSPrivateFiles];
  $: asstCIFiles = [...data.files, ...allCIPrivateFiles];

  let fileSearchOptions: SelectOptionType<string>[] = [];
  let codeInterpreterOptions: SelectOptionType<string>[] = [];
  const fileSearchFilter = data.uploadInfo.getFileSupportFilter({
    code_interpreter: false,
    file_search: true,
    vision: false
  });
  const codeInterpreterFilter = data.uploadInfo.getFileSupportFilter({
    code_interpreter: true,
    file_search: false,
    vision: false
  });
  $: fileSearchOptions = (asstFSFiles || [])
    .filter(fileSearchFilter)
    .map((file) => ({ value: file.file_id, name: file.name }));
  $: codeInterpreterOptions = (asstCIFiles || [])
    .filter(codeInterpreterFilter)
    .map((file) => ({ value: file.file_id, name: file.name }));

  $: fileSearchToolSelect = initialTools.includes('file_search');
  $: codeInterpreterToolSelect = initialTools.includes('code_interpreter');

  // Handle updates from the file upload component.
  const handleFSPrivateFilesChange = (e: CustomEvent<Writable<FileUploadInfo[]>>) => {
    privateUploadFSFileInfo = e.detail;
  };
  const handleCIPrivateFilesChange = (e: CustomEvent<Writable<FileUploadInfo[]>>) => {
    privateUploadCIFileInfo = e.detail;
  };

  // Handle file deletion.
  const removePrivateFiles = async (evt: CustomEvent<Array<number>>) => {
    const files = evt.detail;
    $trashPrivateFileIds = [...$trashPrivateFileIds, ...files];
  };

  const checkForLargeTemperature = (evt: Event) => {
    const target = evt.target as HTMLInputElement;
    const value = target.valueAsNumber;
    if (value > 1.0 && _temperatureValue <= 1.0) {
      if (confirm('Temperatures above 1.0 may lead to nonsensical responses. Are you sure?')) {
        temperatureValue = value;
        _temperatureValue = value;
      } else {
        target.valueAsNumber = _temperatureValue;
        temperatureValue = _temperatureValue;
      }
    } else {
      temperatureValue = value;
      _temperatureValue = value;
    }
  };

  let temperatureValue: number;
  let _temperatureValue: number;
  $: if (
    assistant?.temperature !== undefined &&
    assistant?.temperature !== null &&
    temperatureValue === undefined
  ) {
    temperatureValue = assistant.temperature;
    _temperatureValue = assistant.temperature;
  }
  let reasoningEffortValue: number;
  $: if (
    assistant?.reasoning_effort !== undefined &&
    assistant?.reasoning_effort !== null &&
    reasoningEffortValue === undefined
  ) {
    reasoningEffortValue = assistant.reasoning_effort;
  }
  $: if (
    temperatureValue === undefined &&
    (data.isCreating || assistant?.temperature === undefined || assistant?.temperature === null)
  ) {
    temperatureValue = 0.2;
    _temperatureValue = 0.2;
  }
  $: if (
    reasoningEffortValue === undefined &&
    (data.isCreating ||
      assistant?.reasoning_effort === undefined ||
      assistant?.reasoning_effort === null)
  ) {
    reasoningEffortValue = 1;
  }

  let dropdownOpen = false;
  /**
   * Check if the assistant model supports vision capabilities.
   */
  const updateSelectedModel = (modelValue: string) => {
    dropdownOpen = false;
    selectedModel = modelValue;
  };

  let modelNodes: { [key: string]: HTMLElement } = {};
  let modelHeaders: { [key: string]: string } = {};

  /**
   * Determine if a specific field has changed in the form.
   */
  const checkDirtyField = (
    field: keyof api.CreateAssistantRequest & keyof api.Assistant,
    update: api.CreateAssistantRequest,
    original: api.Assistant | null
  ) => {
    const newValue = update[field];
    const oldValue = original?.[field];

    let dirty = true;

    switch (field) {
      case 'name':
        dirty = newValue !== (oldValue || '');
        break;
      case 'description':
        dirty =
          normalizeNewlines((newValue as string | undefined) || '') !==
          normalizeNewlines((oldValue as string) || '');
        break;
      case 'instructions':
        dirty =
          normalizeNewlines((newValue as string | undefined) || '') !==
          ((oldValue as string) || '');
        break;
      case 'model':
        dirty = newValue !== oldValue;
        break;
      case 'temperature':
        dirty = newValue !== oldValue;
        break;
      case 'reasoning_effort':
        dirty = newValue !== oldValue;
        break;
      case 'published':
        dirty = newValue === undefined ? false : newValue !== !!oldValue;
        break;
      case 'use_latex':
        dirty =
          newValue === undefined
            ? false
            : (preventEdits ? !!assistant?.use_latex : newValue) !== oldValue;
        break;
      case 'use_image_descriptions':
        dirty = newValue === undefined ? false : newValue !== !!oldValue;
        break;
      case 'hide_prompt':
        dirty =
          newValue === undefined
            ? false
            : (preventEdits ? !!assistant?.hide_prompt : newValue) !== oldValue;
        break;
      case 'tools':
        dirty = !setsEqual(
          new Set((newValue as api.Tool[]).map((t) => t.type)),
          new Set(initialTools)
        );
        break;
      default:
        dirty = newValue !== oldValue;
    }

    if (dirty) {
      console.debug(`Field ${field} is dirty: ${oldValue} -> ${newValue}`);
      return true;
    }

    return false;
  };

  /**
   * Check if the form has substantively changed.
   */
  const findAllDirtyFields = (params: api.CreateAssistantRequest) => {
    // Check if the new params are different from the loaded assistant.
    // If the assistant is brand new, ignore simple checkboxes and dropdowns,
    // and only check text entry fields.
    const fields: Array<keyof api.CreateAssistantRequest & keyof api.Assistant> = data.assistantId
      ? [
          'name',
          'description',
          'instructions',
          'interaction_mode',
          'model',
          'published',
          'use_latex',
          'use_image_descriptions',
          'hide_prompt',
          'tools',
          'temperature',
          'reasoning_effort'
        ]
      : ['name', 'description', 'instructions'];

    const modifiedFields: string[] = [];
    for (const field of fields) {
      if (checkDirtyField(field, params, assistant)) {
        modifiedFields.push(field);
      }
    }

    // Check selected files separately since these are handled differently in the form.
    if (
      !setsEqual(
        new Set($selectedCodeInterpreterFiles),
        new Set(data.selectedCodeInterpreterFiles.map((f) => f.file_id))
      )
    ) {
      modifiedFields.push('code interpreter files');
    }
    if (
      !setsEqual(
        new Set($selectedFileSearchFiles),
        new Set(data.selectedFileSearchFiles.map((f) => f.file_id))
      )
    ) {
      modifiedFields.push('file search files');
    }

    return modifiedFields;
  };

  /**
   * Parse data from the assistants form into API request params.
   */
  const parseFormData = (form: HTMLFormElement): api.CreateAssistantRequest => {
    const formData = new FormData(form);
    const body = Object.fromEntries(formData.entries());

    const tools: api.Tool[] = [];
    const fileSearchCodeInterpreterUnusedFiles: number[] = [];
    if (fileSearchToolSelect && supportsFileSearch) {
      tools.push({ type: 'file_search' });
    } else {
      fileSearchCodeInterpreterUnusedFiles.push(...allFSPrivateFiles.map((f) => f.id));
    }
    if (codeInterpreterToolSelect && supportsCodeInterpreter) {
      tools.push({ type: 'code_interpreter' });
    } else {
      fileSearchCodeInterpreterUnusedFiles.push(...allCIPrivateFiles.map((f) => f.id));
    }
    const params = {
      name: preventEdits ? assistant?.name || '' : body.name.toString(),
      interaction_mode: interactionMode,
      description: preventEdits
        ? assistant?.description || ''
        : normalizeNewlines(body.description.toString()),
      instructions: preventEdits
        ? assistant?.instructions || ''
        : normalizeNewlines(body.instructions.toString()),
      model: selectedModel,
      tools,
      code_interpreter_file_ids:
        supportsCodeInterpreter && codeInterpreterToolSelect ? $selectedCodeInterpreterFiles : [],
      file_search_file_ids:
        supportsFileSearch && fileSearchToolSelect ? $selectedFileSearchFiles : [],
      temperature: supportsTemperature ? temperatureValue : null,
      reasoning_effort: supportsReasoning ? reasoningEffortValue : null,
      published: body.published?.toString() === 'on',
      use_latex: body.use_latex?.toString() === 'on',
      use_image_descriptions: body.use_image_descriptions?.toString() === 'on',
      hide_prompt: body.hide_prompt?.toString() === 'on',
      deleted_private_files: [...$trashPrivateFileIds, ...fileSearchCodeInterpreterUnusedFiles]
    };
    return params;
  };

  const deletePrivateFiles = async (fileIds: number[]) => {
    const deletePromises = fileIds.map((fileId) =>
      api.deleteUserFile(fetch, data.class.id, data.me.user!.id, fileId)
    );
    const results = await Promise.all(deletePromises);

    let errorMessage = '';
    results.forEach((result) => {
      if (result.$status >= 300) {
        errorMessage += `Warning: Couldn't delete a private file: ${result.detail}\n`;
      }
    });
    if (errorMessage) {
      sadToast(errorMessage);
    }
  };

  /**
   * Delete the assistant.
   */
  const deleteAssistant = async (evt: CustomEvent) => {
    evt.preventDefault();
    const private_files = [...allFSPrivateFiles, ...allCIPrivateFiles].map((f) => f.id);

    // Show loading message if there are more than 10 files attached
    if ($selectedFileSearchFiles.length + private_files.length >= 10 || private_files.length >= 5) {
      $loadingMessage = 'Deleting assistant. This may take a while.';
    }
    $loading = true;

    if (!data.assistantId) {
      await deletePrivateFiles($trashPrivateFileIds);
      $loadingMessage = '';
      $loading = false;
      sadToast(`Error: Assistant ID not found.`);
      return;
    }

    const result = await api.deleteAssistant(fetch, data.class.id, data.assistantId);
    if (result.$status >= 300) {
      await deletePrivateFiles($trashPrivateFileIds);
      $loadingMessage = '';
      $loading = false;
      sadToast(`Error deleting assistant: ${JSON.stringify(result.detail, null, '  ')}`);
      return;
    }

    await deletePrivateFiles(private_files);
    $loadingMessage = '';
    $loading = false;
    checkForChanges = false;
    happyToast('Assistant deleted');
    await goto(`/group/${data.class.id}/assistant`, { invalidateAll: true });
    return;
  };

  /**
   * Create/save an assistant when form is submitted.
   */
  const submitForm = async (evt: SubmitEvent) => {
    evt.preventDefault();
    $loadingMessage = 'Saving assistant...';
    $loading = true;

    const form = evt.target as HTMLFormElement;
    const params = parseFormData(form);

    if (preventEdits && data.assistantId) {
      const result = await api.updateAssistant(fetch, data.class.id, data.assistantId, {
        published: params.published,
        use_image_descriptions: params.use_image_descriptions
      });
      const expanded = api.expandResponse(result);

      if (expanded.error) {
        $loading = false;
        $loadingMessage = '';
        sadToast(`Could not update the assistant:\n${expanded.error.detail || 'Unknown error'}`);
        return;
      } else {
        $loading = false;
        $loadingMessage = '';
        happyToast('Assistant saved.');
        checkForChanges = false;
        await goto(`/group/${data.class.id}/assistant`, { invalidateAll: true });
        return;
      }
    }

    if (params.file_search_file_ids.length > fileSearchMetadata.max_count) {
      sadToast(`You can only select up to ${fileSearchMetadata.max_count} files for File Search.`);
      $loading = false;
      $loadingMessage = '';
      return;
    }

    if (params.code_interpreter_file_ids.length > codeInterpreterMetadata.max_count) {
      sadToast(
        `You can only select up to ${codeInterpreterMetadata.max_count} files for Code Interpreter.`
      );
      $loading = false;
      $loadingMessage = '';
      return;
    }

    const result = !data.assistantId
      ? await api.createAssistant(fetch, data.class.id, params)
      : await api.updateAssistant(fetch, data.class.id, data.assistantId, params);
    const expanded = api.expandResponse(result);

    if (expanded.error) {
      $loading = false;
      $loadingMessage = '';
      sadToast(`Could not save your response:\n${expanded.error.detail || 'Unknown error'}`);
    } else {
      $loading = false;
      $loadingMessage = '';
      happyToast('Assistant saved');
      checkForChanges = false;
      await goto(`/group/${data.class.id}/assistant`, { invalidateAll: true });
    }
  };

  // Handle file upload
  const handleUpload = (f: File, onProgress: (p: number) => void) => {
    return api.uploadUserFile(data.class.id, data.me.user!.id, f, { onProgress });
  };

  beforeNavigate(async (nav) => {
    if (!assistantForm || !nav.to) {
      return;
    }

    // Confirm before leaving the page, unless we've decided otherwise (e.g. after saving).
    if (checkForChanges) {
      const params = parseFormData(assistantForm);
      const dirtyFields = findAllDirtyFields(params);
      if (dirtyFields.length > 0) {
        if (
          !confirm(
            `Your changes to the following fields have not been saved:\n\n  ${dirtyFields.join(
              ', '
            )}\n\nAre you sure you want to leave this page?`
          )
        ) {
          nav.cancel();
          return;
        }
      }

      // Cancel the automatic navigation so we can handle file deletion first
      nav.cancel();

      // Delete any private files that were uploaded but not saved.
      const filesToDelete = [...$privateUploadFSFileInfo, ...$privateUploadCIFileInfo]
        .filter((f) => f.state === 'success')
        .map((f) => f.response as ServerFile);

      if (filesToDelete.length) {
        $loadingMessage = 'Cleaning up files you uploaded...';
        $loading = true;
        await deletePrivateFiles(filesToDelete.map((f) => f.id));
        $loading = false;
        $loadingMessage = '';
      }

      // Now manually navigate to the intended destination
      checkForChanges = false;
      goto(nav.to.url);
    }
  });
</script>

<div class="h-full w-full overflow-y-auto p-12">
  <div class="flex flex-row justify-between">
    <Heading tag="h2" class="text-3xl font-serif font-medium mb-6 text-blue-dark-40">
      {#if data.isCreating}
        New assistant
      {:else if preventEdits}
        View assistant
      {:else}
        Edit assistant
      {/if}
    </Heading>
    {#if !data.isCreating && !preventEdits}
      <div class="flex items-start shrink-0">
        <Button
          pill
          size="sm"
          class="bg-white border border-red-700 text-red-700 hover:text-white hover:bg-red-700"
          type="button"
          on:click={() => (deleteModal = true)}
          disabled={$loading || uploadingFSPrivate || uploadingCIPrivate}>Delete assistant</Button
        >

        <Modal bind:open={deleteModal} size="xs" autoclose>
          <ConfirmationModal
            warningTitle={`Delete ${data?.assistant?.name || 'this assistant'}?`}
            warningDescription="All threads associated with this assistant will become read-only."
            warningMessage="This action cannot be undone."
            cancelButtonText="Cancel"
            confirmText="delete"
            confirmButtonText="Delete assistant"
            on:cancel={() => (deleteModal = false)}
            on:confirm={deleteAssistant}
          />
        </Modal>
      </div>
    {/if}
  </div>
  {#if preventEdits}
    <div
      class="flex col-span-2 items-center rounded-lg text-white bg-gradient-to-r from-gray-800 to-gray-600 border-gradient-to-r from-gray-800 to-gray-600 p-4 mb-4"
    >
      <LockSolid class="w-8 h-8 mr-3" />
      <span>
        This assistant is locked and cannot be edited. To make changes, create a new assistant. You
        can still publish or unpublish this assistant if you have the necessary permissions. For
        more information, contact your Group's administrator.
      </span>
    </div>
  {/if}

  <form on:submit={submitForm} bind:this={assistantForm}>
    <div class="mb-4">
      <Label class="pb-1" for="name">Name</Label>
      <Input id="name" name="name" value={assistant?.name} disabled={preventEdits} />
    </div>
    <div class="mb-4">
      <Label for="interactionMode">Interaction Mode</Label>
      <Helper class="pb-1">Choose how users will primarily interact with this assistant.</Helper>
      <ButtonGroup>
        <RadioButton value="chat" bind:group={interactionMode} disabled={preventEdits}
          ><div class="flex flex-row gap-2 items-center">
            {#if interactionMode === 'chat'}<MessageDotsSolid
                class="w-6 h-6"
              />{:else}<MessageDotsOutline class="w-6 h-6" />{/if}Text Mode
          </div></RadioButton
        >
        <RadioButton value="live_audio" bind:group={interactionMode} disabled={preventEdits}
          ><div class="flex flex-row gap-2 items-center">
            {#if interactionMode === 'live_audio'}<MicrophoneSolid
                class="w-5 h-5"
              />{:else}<MicrophoneOutline class="w-5 h-5" />{/if}Audio Mode
          </div></RadioButton
        >
      </ButtonGroup>
    </div>
    <div class="mb-4">
      <Label for="model">Model</Label>
      <Helper class="pb-1"
        >Select the model to use for this assistant. You can update your model selection at any
        time. Latest Models will always point to the latest version of the model available. Select a
        Pinned Model Version to continue using a specific model version regardless of future model
        updates. See <a
          href="https://platform.openai.com/docs/models"
          rel="noopener noreferrer"
          target="_blank"
          class="underline">OpenAI's Documentation</a
        > for detailed descriptions of model capabilities.</Helper
      >
      {#if supportsVision && visionSupportOverride === false}
        <div
          class="flex flex-row items-center gap-4 p-4 py-2 mb-2 text-amber-800 border rounded-lg bg-gradient-to-b border-amber-400 from-amber-50 to-amber-100 text-amber-800"
        >
          <div class="flex items-center justify-center relative h-8 w-12">
            <BanOutline class="text-amber-600 w-12 h-12 z-10 absolute" strokeWidth="1.5" />
            <FileImageOutline class="text-stone-400 w-8 h-8" strokeWidth="1" />
          </div>
          <div class="flex flex-col">
            <span class="text-sm font-semibold">Vision capabilities are currently unavailable</span>
            <span class="text-xs"
              >Your AI Provider doesn't support Vision capabilities for this model. We are working
              on adding Vision support. You can still use supported image files with Code
              Interpreter.</span
            >
          </div>
        </div>
      {/if}
      <div class="flex flex-row gap-2">
        <DropdownContainer
          footer
          placeholder={selectedModelName}
          optionNodes={modelNodes}
          optionHeaders={modelHeaders}
          disabled={preventEdits}
          bind:selectedOption={selectedModel}
          bind:dropdownOpen
        >
          <DropdownHeader
            order={1}
            name="latest-models"
            colorClasses="from-orange-dark to-orange"
            topHeader>Latest Models</DropdownHeader
          >
          <ModelDropdownOptions
            modelOptions={latestModelOptions}
            {selectedModel}
            {updateSelectedModel}
            {allowVisionUpload}
            headerClass="latest-models"
            bind:modelNodes
            bind:modelHeaders
          />
          <DropdownHeader
            order={2}
            name="versioned-models"
            colorClasses="from-blue-dark-40 to-blue-dark-30">Pinned Models</DropdownHeader
          >
          <ModelDropdownOptions
            modelOptions={versionedModelOptions}
            {selectedModel}
            {updateSelectedModel}
            {allowVisionUpload}
            headerClass="versioned-models"
            bind:modelNodes
            bind:modelHeaders
            smallNameText
          />
          <div slot="footer">
            <DropdownFooter
              colorClasses="from-gray-800 to-gray-600"
              hoverable
              hoverColorClasses="hover:from-gray-900 hover:to-gray-700"
              link="https://platform.openai.com/docs/models"
              ><div class="flex flex-row justify-between">
                <div class="flex flex-row gap-2">
                  <QuestionCircleSolid /> Unsure which model to choose? Check out OpenAI's documentation
                </div>
                <ArrowUpRightFromSquareOutline />
              </div></DropdownFooter
            >
          </div>
        </DropdownContainer>
        {#if allowVisionUpload}
          <Badge
            class="flex flex-row items-center gap-x-2 py-0.5 px-2 border rounded-lg text-xs normal-case {finalVisionSupport
              ? 'bg-gradient-to-b border-green-400 from-emerald-100 to-emerald-200 text-green-800'
              : 'border-gray-100 bg-gray-50 text-gray-600'}"
            >{#if finalVisionSupport}<ImageOutline size="sm" />{:else}<CloseOutline
                size="sm"
              />{/if}
            <div class="flex flex-col">
              <div>{finalVisionSupport ? 'Vision' : 'No Vision'}</div>
              <div>capabilities</div>
            </div></Badge
          >
        {/if}
      </div>
    </div>

    <div class="col-span-2 mb-4">
      <Label for="description">Description</Label>
      <Helper class="pb-1"
        >Describe what this assistant does. This information is <strong>not</strong> included in the
        prompt, but <strong>is</strong> shown to users.</Helper
      >
      <Textarea
        id="description"
        name="description"
        value={assistant?.description || ''}
        disabled={preventEdits}
      />
    </div>
    <div class="col-span-2 mb-4">
      <Label for="instructions">Instructions</Label>
      <Helper class="pb-1"
        >This is the prompt the language model will use to generate responses.</Helper
      >
      <Textarea
        id="instructions"
        name="instructions"
        rows={6}
        value={assistant?.instructions}
        disabled={preventEdits}
      />
    </div>
    <div class="col-span-2 mb-4">
      <Checkbox
        id="hide_prompt"
        name="hide_prompt"
        disabled={preventEdits}
        checked={(assistant ? assistant.hide_prompt : false) || false}>Hide Prompt</Checkbox
      >
      <Helper
        >Hide the prompt from other users. When checked, only the moderation team and the
        assistant's creator will be able to see this prompt.</Helper
      >
    </div>
    <div class="col-span-2 mb-4">
      {#if interactionMode === 'chat'}
        <Checkbox
          id="use_latex"
          name="use_latex"
          disabled={preventEdits}
          checked={(assistant ? assistant.use_latex : true) || false}>Use LaTeX</Checkbox
        >
        <Helper>Enable LaTeX formatting for assistant responses.</Helper>
      {:else}
        <div class="flex flex-col gap-y-1">
          <Badge
            class="flex flex-row items-center gap-x-2 py-0.5 px-2 border rounded-lg text-xs normal-case bg-gradient-to-b border-gray-400 from-gray-100 to-gray-200 text-gray-800 shrink-0 max-w-fit"
            ><CloseOutline size="sm" />
            <div>No LaTeX formatting for assistant responses</div>
          </Badge>
          <Helper
            >This interaction mode does not support LaTeX formatting for assistant responses. To use
            LaTeX formatting, switch to Text Mode.</Helper
          >
        </div>
      {/if}
    </div>
    <div class="col-span-2 mb-4">
      <Label for="tools">Tools</Label>
      <Helper>Select tools available to the assistant when generating a response.</Helper>
    </div>
    {#if !supportsFileSearch}
      <div class="col-span-2 mb-3">
        <div class="flex flex-col gap-y-1">
          <Badge
            class="flex flex-row items-center gap-x-2 py-0.5 px-2 border rounded-lg text-xs normal-case bg-gradient-to-b border-gray-400 from-gray-100 to-gray-200 text-gray-800 shrink-0 max-w-fit"
            ><CloseOutline size="sm" />
            <div>No File Search capabilities</div>
          </Badge>
          <Helper
            >This model does not support File Search capabilities. To use File Search, select a
            different model.</Helper
          >
        </div>
      </div>
    {:else}
      <div class="col-span-2 mb-4">
        <Checkbox
          id={fileSearchMetadata.value}
          name={fileSearchMetadata.value}
          checked={supportsFileSearch && (fileSearchToolSelect || false)}
          disabled={!supportsFileSearch || preventEdits}
          on:change={() => {
            fileSearchToolSelect = !fileSearchToolSelect;
          }}>{fileSearchMetadata.name}</Checkbox
        >
        <Helper>{fileSearchMetadata.description}</Helper>
      </div>
    {/if}
    <div class="col-span-2 mb-4">
      {#if !supportsCodeInterpreter}
        <div class="flex flex-col gap-y-1">
          <Badge
            class="flex flex-row items-center gap-x-2 py-0.5 px-2 border rounded-lg text-xs normal-case bg-gradient-to-b border-gray-400 from-gray-100 to-gray-200 text-gray-800 shrink-0 max-w-fit"
            ><CloseOutline size="sm" />
            <div>No Code Interpreter capabilities</div>
          </Badge>
          <Helper
            >This model does not support Code Interpreter capabilities. To use Code Interpreter,
            select a different model.</Helper
          >
        </div>
      {:else}
        <Checkbox
          id={codeInterpreterMetadata.value}
          name={codeInterpreterMetadata.value}
          disabled={preventEdits || !supportsCodeInterpreter}
          checked={supportsCodeInterpreter && (codeInterpreterToolSelect || false)}
          on:change={() => {
            codeInterpreterToolSelect = !codeInterpreterToolSelect;
          }}>{codeInterpreterMetadata.name}</Checkbox
        >
        <Helper>{codeInterpreterMetadata.description}</Helper>
      {/if}
    </div>

    {#if fileSearchToolSelect && supportsFileSearch}
      <div class="col-span-2 mb-4">
        <Label for="selectedFileSearchFiles">{fileSearchMetadata.name} Files</Label>
        <Helper class="pb-1"
          >Select which files this assistant should use for {fileSearchMetadata.name}. You can
          select up to {fileSearchMetadata.max_count} files. You can also upload private files specific
          to this assistant. If you want to make files available for the entire group, upload them in
          the Manage Group page.</Helper
        >
        <MultiSelectWithUpload
          name="selectedFileSearchFiles"
          items={fileSearchOptions}
          bind:value={selectedFileSearchFiles}
          disabled={$loading ||
            !handleUpload ||
            uploadingFSPrivate ||
            preventEdits ||
            !supportsFileSearch}
          privateFiles={allFSPrivateFiles}
          uploading={uploadingFSPrivate}
          upload={handleUpload}
          accept={data.uploadInfo.fileTypes({
            file_search: true,
            code_interpreter: false,
            vision: false
          })}
          maxSize={data.uploadInfo.class_file_max_size}
          maxCount={fileSearchMetadata.max_count}
          uploadType="File Search"
          on:error={(e) => sadToast(e.detail.message)}
          on:change={handleFSPrivateFilesChange}
          on:delete={removePrivateFiles}
        />
      </div>
    {/if}

    {#if codeInterpreterToolSelect && supportsCodeInterpreter}
      <div class="col-span-2 mb-4">
        <Label for="selectedCodeInterpreterFiles">{codeInterpreterMetadata.name} Files</Label>
        <Helper class="pb-1"
          >Select which files this assistant should use for {codeInterpreterMetadata.name}. You can
          select up to {codeInterpreterMetadata.max_count} files. You can also upload private files specific
          to this assistant. If you want to make files available for the entire group, upload them in
          the Manage Group page.</Helper
        >
        <MultiSelectWithUpload
          name="selectedCodeInterpreterFiles"
          items={codeInterpreterOptions}
          bind:value={selectedCodeInterpreterFiles}
          disabled={$loading ||
            !handleUpload ||
            uploadingCIPrivate ||
            preventEdits ||
            !supportsCodeInterpreter}
          privateFiles={allCIPrivateFiles}
          uploading={uploadingCIPrivate}
          upload={handleUpload}
          accept={data.uploadInfo.fileTypes({
            file_search: false,
            code_interpreter: true,
            vision: false
          })}
          maxSize={data.uploadInfo.class_file_max_size}
          maxCount={codeInterpreterMetadata.max_count}
          uploadType="Code Interpreter"
          on:error={(e) => sadToast(e.detail.message)}
          on:change={handleCIPrivateFilesChange}
          on:delete={removePrivateFiles}
        />
      </div>
    {/if}

    <div class="col-span-2 mb-4">
      <Checkbox
        id="published"
        disabled={!canPublish && !assistant?.published}
        name="published"
        checked={!!assistant?.published}>Publish</Checkbox
      >
      {#if !canPublish}
        <Helper
          >You do not have permissions to change the published status of this assistant. Contact
          your administrator if you need to share this assistant.</Helper
        >
      {:else}
        <Helper
          >By default only you can see and interact with this assistant. If you would like to share
          the assistant with the rest of your group, select this option.</Helper
        >
      {/if}
    </div>

    {#if visionSupportOverride === false}
      <div class="col-span-2 mb-4">
        <Checkbox
          id="use_image_descriptions"
          name="use_image_descriptions"
          class="mb-1"
          checked={!!assistant?.use_image_descriptions}
          ><div class="flex flex-row gap-1">
            <DropdownBadge
              extraClasses="border-amber-400 from-amber-100 to-amber-200 text-amber-800 py-0 px-1"
              ><span slot="name">Experimental</span></DropdownBadge
            >
            <div>Enable Vision capabilities through Image Descriptions</div>
          </div></Checkbox
        >
        <Helper
          >Your AI Provider doesn't support direct image analysis for this model. Enable this option
          to try a new experimental feature that uses image descriptions to provide Vision
          capabilities. This feature is still under active development and might produce unexpected
          or inaccurate results. To share your thoughts or report any issues, <a
            href="https://airtable.com/appR9m6YfvPTg1H3d/pagS1VLdLrPSbeqoN/form"
            class="underline"
            rel="noopener noreferrer"
            target="_blank">use this form</a
          >.
        </Helper>
      </div>
    {/if}

    <div class="w-8/9 my-5">
      <Accordion>
        <AccordionItem
          paddingDefault="px-5 py-3"
          defaultClass="px-6 py-4 flex items-center justify-between w-full font-medium text-left rounded border-gray-200 dark:border-gray-700"
          activeClass="rounded-b-none"
          borderOpenClass="rounded-b-lg border-s border-e"
        >
          <span slot="header"
            ><div class="flex-row flex items-center space-x-2 py-0">
              <div><CogOutline size="md" strokeWidth="2" /></div>
              <div class="text-sm">Advanced Options</div>
            </div></span
          >
          <div class="flex flex-col gap-4 px-1">
            {#if supportsTemperature}
              <Label for="temperature">Temperature</Label>
              <Helper class="pb-1"
                >Select the model's "temperature," a setting from 0 to 2 that controls how creative
                or predictable the assistant's responses are. For reliable, focused answers, choose
                a temperature closer to 0.2. For more varied or creative responses, try a setting
                closer to 1. Avoid setting the temperature much above 1 unless you need very
                experimental responses, as it may lead to less predictable and more random answers.
                You can change this setting anytime.</Helper
              >
              <div class="mt-2 flex flex-row justify-between">
                <div class="flex flex-row gap-1 items-center text-sm">
                  <ArrowLeftOutline />
                  <div>More focused</div>
                </div>
                <Badge
                  class="flex flex-row items-center gap-x-2 py-0.5 px-2 border rounded-md text-xs normal-case bg-gradient-to-b border-sky-400 from-sky-100 to-sky-200 text-sky-800 shrink-0"
                >
                  <div>Temperature: {temperatureValue.toFixed(1)}</div>
                </Badge>
                <div class="flex flex-row gap-1 items-center text-sm">
                  <div>More creative</div>
                  <ArrowRightOutline />
                </div>
              </div>
              <Range
                id="temperature"
                name="temperature"
                min="0"
                max="2"
                bind:value={temperatureValue}
                step="0.1"
                disabled={preventEdits}
                on:change={checkForLargeTemperature}
              />
              <div class="grid grid-cols-20 gap-0 mx-2">
                <button
                  type="button"
                  class="ml-1 col-span-4 flex flex-col items-center justify-start bg-transparent border-0"
                  on:click={() => {
                    temperatureValue = 0.2;
                    _temperatureValue = 0.2;
                  }}
                  on:keydown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      temperatureValue = 0.2;
                      _temperatureValue = 0.2;
                    }
                  }}
                >
                  <HeartSolid class="text-gray-500 max-w-fit" />
                  <div class="mt-1 mx-10 text-center text-sm text-wrap">Default (recommended)</div>
                </button>
                <button
                  type="button"
                  class="col-start-6 col-span-4 flex flex-col items-center justify-start bg-transparent border-0"
                  on:click={() => {
                    temperatureValue = 0.7;
                    _temperatureValue = 0.7;
                  }}
                  on:keydown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      temperatureValue = 0.7;
                      _temperatureValue = 0.7;
                    }
                  }}
                >
                  <LightbulbSolid class="text-gray-500 max-w-fit" />
                  <div class="mt-1 mx-10 text-center text-sm text-wrap">
                    Great for creative tasks and brainstorming
                  </div>
                </button>
                <div
                  class="col-start-12 col-span-9 rounded-md border text-center bg-gradient-to-b border-amber-400 from-amber-100 to-amber-200 text-amber-800 h-6 text-sm -mr-2 -ml-2 h-fit py-1"
                >
                  Output may be unpredictable
                </div>
              </div>
            {/if}
            {#if supportsReasoning}
              <Label for="reasoning-effort">Reasoning effort</Label>
              <Helper class="pb-1"
                >Select your desired reasoning effort, which gives the model guidance on how much
                time it should spend "reasoning" before creating a response to the prompt. You can
                specify one of <span class="font-mono">low</span>,
                <span class="font-mono">medium</span>, or
                <span class="font-mono">high</span>
                for this setting, where <span class="font-mono">low</span> will favor speed, and
                <span class="font-mono">high</span>
                will favor more complete reasoning at the cost of slower responses. The default value
                is
                <span class="font-mono">medium</span>, which is a balance between speed and
                reasoning accuracy. You can change this setting anytime.</Helper
              >
              <Range
                id="reasoning-effort"
                name="reasoning-effort"
                min="0"
                max="2"
                bind:value={reasoningEffortValue}
                step="1"
                disabled={preventEdits}
              />
              <div class="mt-2 flex flex-row justify-between">
                <p class="text-sm">low</p>
                <p class="text-sm">medium</p>
                <p class="text-sm">high</p>
              </div>
            {/if}
          </div>
        </AccordionItem>
      </Accordion>
    </div>

    <input type="hidden" name="assistantId" value={assistant?.id} />

    <div class="border-t pt-4 mt-4 flex items-center col-span-2">
      <Button
        pill
        class="bg-orange border border-orange text-white hover:bg-orange-dark"
        type="submit"
        disabled={$loading || uploadingFSPrivate || uploadingCIPrivate}>Save</Button
      >
      <Button
        disabled={$loading || uploadingFSPrivate || uploadingCIPrivate}
        href={`/group/${data.class.id}/assistant`}
        color="red"
        pill
        class="bg-blue-light-50 border rounded-full border-blue-dark-40 text-blue-dark-50 hover:bg-blue-light-40 ml-4"
        >Cancel</Button
      >
    </div>
  </form>
</div>
