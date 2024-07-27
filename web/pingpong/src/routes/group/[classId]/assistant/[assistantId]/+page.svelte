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
    Dropdown,
    DropdownItem,
    Badge
  } from 'flowbite-svelte';
  import type { Tool, ServerFile, FileUploadInfo } from '$lib/api';
  import { beforeNavigate, goto } from '$app/navigation';
  import * as api from '$lib/api';
  import { setsEqual } from '$lib/set';
  import { happyToast, sadToast } from '$lib/toast';
  import { normalizeNewlines } from '$lib/content.js';
  import {
    ChevronDownOutline,
    CloseOutline,
    ImageOutline,
    ExclamationCircleOutline,
    QuestionCircleSolid,
    ArrowUpRightFromSquareOutline,
  } from 'flowbite-svelte-icons';
  import MultiSelectWithUpload from '$lib/components/MultiSelectWithUpload.svelte';
  import { writable, type Writable } from 'svelte/store';
  import { loading, loadingMessage } from '$lib/stores/general';
  import ModelDropdownOptions from '$lib/components/ModelDropdownOptions.svelte';
  export let data;

  // Flag indicating whether we should check for changes before navigating away.
  let checkForChanges = true;
  let assistantForm: HTMLFormElement;
  let deleteModal = false;

  $: assistant = data.assistant;
  $: canPublish = data.grants.canPublishAssistants;

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
    max_count: 50
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
  $: latestModelOptions = (data.models.filter((model) => model.is_latest) || []).map((model) => ({
    value: model.id,
    name: model.name,
    description: model.description,
    supports_vision: model.supports_vision,
    is_new: model.is_new,
    highlight: model.highlight
  }));
  let selectedModel = '';
  $: if (latestModelOptions.length > 0 && !selectedModel) {
    selectedModel = assistant?.model || latestModelOptions[0].value;
  }
  $: selectedModelName = modelNameDict[selectedModel];
  $: versionedModelOptions = (data.models.filter((model) => !model.is_latest) || []).map(
    (model) => ({
      value: model.id,
      name: model.name,
      description: model.description,
      supports_vision: model.supports_vision,
      is_new: model.is_new,
      highlight: model.highlight
    })
  );
  $: supportVisionModels = (data.models.filter((model) => model.supports_vision) || []).map(
    (model) => model.id
  );
  $: supportsVision = supportVisionModels.includes(selectedModel);
  $: allowVisionUpload = !!data?.grants?.isSupervisor;
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

  let dropdownOpen = false;
  /**
   * Check if the assistant model supports vision capabilities.
   */
  const updateSelectedModel = (modelValue: string) => {
    dropdownOpen = false;
    selectedModel = modelValue;
  };

  let modelNodes: { [key: string]: HTMLElement } = {};
  $: currentNode = modelNodes[selectedModel] || null;
  $: if (currentNode) {
    currentNode.scrollIntoView({ behavior: 'instant', block: 'nearest' });
  }

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
      case 'published':
        dirty = newValue === undefined ? false : newValue !== !!oldValue;
        break;
      case 'use_latex':
        dirty = newValue === undefined ? false : newValue !== oldValue;
        break;
      case 'hide_prompt':
        dirty = newValue === undefined ? false : newValue !== oldValue;
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
          'model',
          'published',
          'use_latex',
          'hide_prompt',
          'tools'
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
    if (fileSearchToolSelect) {
      tools.push({ type: 'file_search' });
    }
    if (codeInterpreterToolSelect) {
      tools.push({ type: 'code_interpreter' });
    }

    const params = {
      name: body.name.toString(),
      description: normalizeNewlines(body.description.toString()),
      instructions: normalizeNewlines(body.instructions.toString()),
      model: selectedModel,
      tools,
      code_interpreter_file_ids: codeInterpreterToolSelect ? $selectedCodeInterpreterFiles : [],
      file_search_file_ids: fileSearchToolSelect ? $selectedFileSearchFiles : [],
      published: body.published?.toString() === 'on',
      use_latex: body.use_latex?.toString() === 'on',
      hide_prompt: body.hide_prompt?.toString() === 'on',
      deleted_private_files: data.assistantId ? $trashPrivateFileIds : []
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
  const deleteAssistant = async (evt: MouseEvent) => {
    evt.preventDefault();
    const private_files = [
      ...data.selectedCodeInterpreterFiles.filter((f) => f.private),
      ...privateFSSessionFiles,
      ...privateCISessionFiles
    ].map((f) => f.id);

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
    $loading = true;

    const form = evt.target as HTMLFormElement;
    const params = parseFormData(form);

    if (params.file_search_file_ids.length > fileSearchMetadata.max_count) {
      sadToast(`You can only select up to ${fileSearchMetadata.max_count} files for File Search.`);
      $loading = false;
      return;
    }

    if (params.code_interpreter_file_ids.length > codeInterpreterMetadata.max_count) {
      sadToast(
        `You can only select up to ${codeInterpreterMetadata.max_count} files for Code Interpreter.`
      );
      $loading = false;
      return;
    }

    const result = !data.assistantId
      ? await api.createAssistant(fetch, data.class.id, params)
      : await api.updateAssistant(fetch, data.class.id, data.assistantId, params);
    const expanded = api.expandResponse(result);

    if (expanded.error) {
      // TODO(jnu): error message is hard to read right now, improve this.
      $loading = false;
      sadToast(`Error: ${JSON.stringify(expanded.error, null, '  ')}`);
    } else {
      $loading = false;
      happyToast('Assistant saved');
      checkForChanges = false;
      await goto(`/group/${data.class.id}/assistant`, { invalidateAll: true });
    }
  };

  // Handle file upload
  const handleUpload = (f: File, onProgress: (p: number) => void) => {
    return api.uploadUserFile(data.class.id, data.me.user!.id, f, { onProgress });
  };

  beforeNavigate((nav) => {
    if (!assistantForm) {
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
    }
  });
</script>

<div class="h-full w-full overflow-y-auto p-12">
  <div class="flex flex-row justify-between">
    <Heading tag="h2" class="text-3xl font-serif font-medium mb-6 text-blue-dark-40">
      {#if data.isCreating}
        New assistant
      {:else}
        Edit assistant
      {/if}
    </Heading>
    {#if !data.isCreating}
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
          <div class="text-center">
            <ExclamationCircleOutline class="mx-auto mb-4 text-red-600 w-12 h-12" />
            <h3 class="mb-5 text-xl text-black font-bold">
              Delete {data?.assistant?.name || 'this assistant'}?
            </h3>
            <h4 class="mb-5 text-sm text-black font-normal">
              All threads associated with this assistant will become read-only. This action cannot
              be undone.
            </h4>
            <Button pill color="alternative">Cancel</Button>
            <Button pill color="red" on:click={deleteAssistant}>Delete</Button>
          </div>
        </Modal>
      </div>
    {/if}
  </div>

  <form on:submit={submitForm} bind:this={assistantForm}>
    <div class="mb-4">
      <Label class="pb-1" for="name">Name</Label>
      <Input label="name" id="name" name="name" value={assistant?.name} />
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
      <div class="flex flex-row gap-2">
        <button
          id="model"
          name="model"
          class="flex flex-row grow justify-between items-center text-gray-900 bg-gray-50 border border-gray-300 rounded-lg focus:ring-primary-500 focus:border-primary-500 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white dark:focus:ring-primary-500 dark:focus:border-primary-500 text-sm p-2.5"
          type="button"
        >
          {selectedModelName}
          <ChevronDownOutline class="w-6 h-6 ms-2" />
        </button>
        <Dropdown
          class="py-0 rounded-lg"
          containerClass="dropdown-container w-1/2 border border-gray-300 flex flex-col"
          placement="bottom-start"
          bind:open={dropdownOpen}
        >
          <div class="relative max-h-80">
            <div
              class="overflow-y-auto overscroll-contain rounded-t-lg flex-grow max-h-80 relative"
            >
              <div
                class="sticky top-0 z-10 bg-gradient-to-r from-orange-dark to-orange drop-shadow-md"
              >
                <div
                  class="absolute inset-x-0 -top-96 h-96 bg-gradient-to-r from-orange-dark to-orange"
                ></div>
                <DropdownItem disabled defaultClass="font-normal py-2 px-4 text-sm text-white"
                  >Latest Models</DropdownItem
                >
              </div>
              <div class="relative z-0">
                <ModelDropdownOptions
                  modelOptions={latestModelOptions}
                  selectedModel={selectedModel}
                  updateSelectedModel={updateSelectedModel}
                  allowVisionUpload={allowVisionUpload}
                  bind:modelNodes={modelNodes}
                />
              </div>
              <div
                class="sticky top-0 z-10 bg-gradient-to-r from-blue-dark-40 to-blue-dark-30 drop-shadow-md"
              >
                <DropdownItem disabled defaultClass="font-normal py-2 px-4 text-sm text-white"
                  >Pinned Models (advanced)</DropdownItem
                >
              </div>
              <ModelDropdownOptions
                  modelOptions={versionedModelOptions}
                  selectedModel={selectedModel}
                  updateSelectedModel={updateSelectedModel}
                  allowVisionUpload={allowVisionUpload}
                  bind:modelNodes={modelNodes}
                  smallNameText
                />
            </div>
          </div>
          <a
            href="https://platform.openai.com/docs/models/models-overview"
            rel="noopener noreferrer"
            target="_blank"
            ><DropdownItem
              class="bg-gradient-to-r from-gray-800 to-gray-600 text-white hover:from-gray-900 hover:to-gray-700 border-t rounded-b-lg"
              ><div class="flex flex-row justify-between">
                <div class="flex flex-row gap-2">
                  <QuestionCircleSolid /> Unsure which model to choose? Check out OpenAI's documentation
                </div>
                <ArrowUpRightFromSquareOutline />
              </div></DropdownItem
            ></a
          >
        </Dropdown>
        {#if allowVisionUpload}
          <Badge
            class='flex flex-row items-center gap-x-2 py-0.5 px-2 border rounded-lg text-xs normal-case {supportsVision
              ? 'bg-gradient-to-b border-green-400 from-emerald-100 to-emerald-200 text-green-800'
              : 'border-gray-100 bg-gray-50 text-gray-600'}'
            >{#if supportsVision}<ImageOutline size="sm" />{:else}<CloseOutline size="sm" />{/if}
            <div class="flex flex-col">
              <div>{supportsVision ? 'Vision' : 'No Vision'}</div>
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
        label="description"
        id="description"
        name="description"
        value={assistant?.description}
      />
    </div>
    <div class="col-span-2 mb-4">
      <Label for="instructions">Instructions</Label>
      <Helper class="pb-1"
        >This is the prompt the language model will use to generate responses.</Helper
      >
      <Textarea
        label="instructions"
        id="instructions"
        name="instructions"
        rows="6"
        value={assistant?.instructions}
      />
    </div>
    <div class="col-span-2 mb-4">
      <Checkbox
        id="hide_prompt"
        name="hide_prompt"
        checked={(assistant ? assistant.hide_prompt : false) || false}>Hide Prompt</Checkbox
      >
      <Helper
        >Hide the prompt from other users. When checked, only the moderation team and the
        assistant's creator will be able to see this prompt.</Helper
      >
    </div>
    <div class="col-span-2 mb-4">
      <Checkbox
        label="use_latex"
        id="use_latex"
        name="use_latex"
        checked={(assistant ? assistant.use_latex : true) || false}>Use LaTeX</Checkbox
      >
      <Helper>Enable LaTeX formatting for assistant responses.</Helper>
    </div>
    <div class="col-span-2 mb-4">
      <Label for="tools">Tools</Label>
      <Helper>Select tools available to the assistant when generating a response.</Helper>
    </div>
    <div class="col-span-2 mb-4">
      <Checkbox
        id={fileSearchMetadata.value}
        name={fileSearchMetadata.value}
        checked={fileSearchToolSelect || false}
        on:change={() => {
          fileSearchToolSelect = !fileSearchToolSelect;
        }}>{fileSearchMetadata.name}</Checkbox
      >
      <Helper>{fileSearchMetadata.description}</Helper>
    </div>
    <div class="col-span-2 mb-4">
      <Checkbox
        id={codeInterpreterMetadata.value}
        name={codeInterpreterMetadata.value}
        checked={codeInterpreterToolSelect || false}
        on:change={() => {
          codeInterpreterToolSelect = !codeInterpreterToolSelect;
        }}>{codeInterpreterMetadata.name}</Checkbox
      >
      <Helper>{codeInterpreterMetadata.description}</Helper>
    </div>

    {#if fileSearchToolSelect}
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
          disabled={$loading || !handleUpload || uploadingFSPrivate}
          privateFiles={allFSPrivateFiles}
          uploading={uploadingFSPrivate}
          upload={handleUpload}
          accept={data.uploadInfo.fileTypes({
            file_search: true,
            code_interpreter: false,
            vision: false
          })}
          maxCount={fileSearchMetadata.max_count}
          uploadType="File Search"
          on:error={(e) => sadToast(e.detail.message)}
          on:change={handleFSPrivateFilesChange}
          on:delete={removePrivateFiles}
        />
      </div>
    {/if}

    {#if codeInterpreterToolSelect}
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
          disabled={$loading || !handleUpload || uploadingCIPrivate}
          privateFiles={allCIPrivateFiles}
          uploading={uploadingCIPrivate}
          upload={handleUpload}
          accept={data.uploadInfo.fileTypes({
            file_search: false,
            code_interpreter: true,
            vision: false
          })}
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
        label="published"
        id="published"
        disabled={!canPublish && !assistant?.published}
        name="published"
        checked={!!assistant?.published}>Publish</Checkbox
      >
      {#if !canPublish}
        <Helper
          >Publishing assistants has been disabled for this group. Contact your admin if you need to
          share this assistant.</Helper
        >
      {:else}
        <Helper
          >By default only you can see and interact with this assistant. If you would like to share
          the assistant with the rest of your group, select this option.</Helper
        >
      {/if}
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
