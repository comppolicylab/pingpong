<script lang="ts">
  import { afterNavigate, goto } from '$app/navigation';
  import { navigating, page } from '$app/stores';
  import ChatInput, { type ChatInputMessage } from '$lib/components/ChatInput.svelte';
  import {
    Button,
    Span,
    Modal,
    Dropdown,
    DropdownItem,
    DropdownDivider,
    Tooltip
  } from 'flowbite-svelte';
  import {
    EyeSlashOutline,
    LockSolid,
    MicrophoneOutline,
    CirclePlusSolid,
    MicrophoneSlashOutline,
    BadgeCheckOutline,
    UsersOutline,
    ChevronSortOutline,
    CheckCircleSolid,
    UserOutline,
    PaperPlaneOutline,
    UsersSolid
  } from 'flowbite-svelte-icons';
  import { sadToast } from '$lib/toast';
  import * as api from '$lib/api';
  import { errorMessage } from '$lib/errors';
  import type { Assistant, FileUploadPurpose } from '$lib/api';
  import { loading, isFirefox } from '$lib/stores/general';
  import ModeratorsTable from '$lib/components/ModeratorsTable.svelte';
  import Logo from '$lib/components/Logo.svelte';

  /**
   * Application data.
   */
  export let data;

  // Get info about assistant provenance
  const getAssistantMetadata = (assistant: Assistant) => {
    const isCourseAssistant = assistant.endorsed;
    const isMyAssistant = assistant.creator_id === data.me.user?.id;
    const creator = data.assistantCreators[assistant.creator_id]?.name || 'Unknown creator';
    const willDisplayUserInfo = data.class.private
      ? false
      : (assistant.should_record_user_information ?? false);
    return {
      creator: isCourseAssistant ? 'Moderation Team' : creator,
      isCourseAssistant,
      isMyAssistant,
      willDisplayUserInfo
    };
  };

  let userTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  $: isPrivate = data.class.private || false;
  // Currently selected assistant.
  $: assistants = data?.assistants || [];
  $: teachers = data?.supervisors || [];
  $: courseAssistants = assistants.filter((asst) => asst.endorsed);
  $: myAssistantsAll = assistants.filter((asst) => asst.creator_id === data.me.user?.id);
  $: myAssistants = myAssistantsAll.filter((asst) => !asst.endorsed);
  $: otherAssistantsAll = assistants.filter((asst) => asst.creator_id !== data.me.user?.id);
  $: otherAssistants = otherAssistantsAll.filter((asst) => !asst.endorsed);
  $: assistant = data?.assistants[0] || {};
  $: assistantMeta = getAssistantMetadata(assistant);
  // Whether billing is set up for the class (which controls everything).
  $: isConfigured = data?.hasAssistants && data?.hasAPIKey;
  $: parties = data.me.status === 'anonymous' ? '' : data.me.user?.id ? `${data.me.user.id}` : '';
  // The assistant ID from the URL.
  $: linkedAssistant = parseInt($page.url.searchParams.get('assistant') || '0', 10);
  let useImageDescriptions = false;
  $: {
    if (linkedAssistant && assistants) {
      const selectedAssistant = (assistants || []).find((asst) => asst.id === linkedAssistant);
      if (selectedAssistant) {
        assistant = selectedAssistant;
        useImageDescriptions = assistant.use_image_descriptions || false;
      }
    }
  }
  $: supportsFileSearch = assistant.tools?.includes('file_search') || false;
  $: supportsCodeInterpreter = assistant.tools?.includes('code_interpreter') || false;
  let supportsVision = false;
  $: {
    const supportVisionModels = (data.modelInfo.filter((model) => model.supports_vision) || []).map(
      (model) => model.id
    );
    supportsVision = supportVisionModels.includes(assistant.model);
  }
  let visionSupportOverride: boolean | undefined;
  $: {
    visionSupportOverride =
      data.class.ai_provider === 'azure'
        ? data.modelInfo.find((model) => model.id === assistant.model)?.azure_supports_vision
        : undefined;
  }
  $: allowVisionUpload = true;
  let showModerators = false;

  // Handle file upload
  const handleUpload = (
    f: File,
    onProgress: (p: number) => void,
    purpose: FileUploadPurpose = 'assistants',
    useImageDescriptions: boolean = false
  ) => {
    return api.uploadUserFile(
      data.class.id,
      data.me.user!.id,
      f,
      { onProgress },
      purpose,
      useImageDescriptions
    );
  };

  // Handle file removal
  const handleRemove = async (fileId: number) => {
    const result = await api.deleteUserFile(fetch, data.class.id, data.me.user!.id, fileId);
    if (api.isErrorResponse(result)) {
      sadToast(`Failed to delete file. Error: ${result.detail || 'unknown error'}`);
      throw new Error(result.detail || 'unknown error');
    }
  };

  const handleAudioThreadCreate = async (e: Event) => {
    $loading = true;
    const partyIds = parties ? parties.split(',').map((id) => parseInt(id, 10)) : [];
    try {
      const newThread = api.explodeResponse(
        await api.createAudioThread(fetch, data.class.id, {
          assistant_id: assistant.id,
          parties: partyIds,
          timezone: userTimezone
        })
      );
      data.threads = [newThread as api.Thread, ...data.threads];
      $loading = false;
      await goto(`/group/${$page.params.classId}/thread/${newThread.id}`);
    } catch (e) {
      $loading = false;
      sadToast(
        `Failed to create thread. Error: ${errorMessage(e, "Something went wrong while creating your conversation. If the issue persists, check PingPong's status page for updates.")}`
      );
    }
  };

  const handleChatThreadCreate = async (e: Event) => {
    $loading = true;
    const partyIds = parties ? parties.split(',').map((id) => parseInt(id, 10)) : [];
    const tools: api.Tool[] = [];
    if (supportsFileSearch) {
      tools.push({ type: 'file_search' });
    }
    if (supportsCodeInterpreter) {
      tools.push({ type: 'code_interpreter' });
    }
    try {
      const newThread = api.explodeResponse(
        await api.createThread(
          fetch,
          data.class.id,
          {
            assistant_id: assistant.id,
            parties: partyIds,
            message: null,
            tools_available: tools,
            code_interpreter_file_ids: [],
            file_search_file_ids: [],
            vision_file_ids: [],
            vision_image_descriptions: [],
            timezone: userTimezone
          },
          data.shareTokenInfo
        )
      );
      data.threads = [newThread as api.Thread, ...data.threads];
      $loading = false;
      await goto(`/group/${$page.params.classId}/thread/${newThread.id}`);
    } catch (e) {
      $loading = false;
      sadToast(
        `Failed to create thread. Error: ${errorMessage(e, "Something went wrong while creating your conversation. If the issue persists, check PingPong's status page for updates.")}`
      );
    }
  };

  // Handle form submission
  const handleSubmit = async (e: CustomEvent<ChatInputMessage>) => {
    $loading = true;
    const form = e.detail;
    if (!form.message) {
      $loading = false;
      form.callback({
        success: false,
        errorMessage: 'Please enter a message.',
        message_sent: false
      });
      return;
    }

    const partyIds = parties ? parties.split(',').map((id) => parseInt(id, 10)) : [];
    const tools: api.Tool[] = [];
    if (supportsFileSearch) {
      tools.push({ type: 'file_search' });
    }
    if (supportsCodeInterpreter) {
      tools.push({ type: 'code_interpreter' });
    }

    try {
      const newThread = api.explodeResponse(
        await api.createThread(
          fetch,
          data.class.id,
          {
            assistant_id: assistant.id,
            parties: partyIds,
            message: form.message,
            tools_available: tools,
            code_interpreter_file_ids: form.code_interpreter_file_ids,
            file_search_file_ids: form.file_search_file_ids,
            vision_file_ids: form.vision_file_ids,
            vision_image_descriptions: form.visionFileImageDescriptions
          },
          data.shareTokenInfo
        )
      );
      data.threads = [newThread as api.Thread, ...data.threads];
      $loading = false;
      form.callback({ success: true, errorMessage: null, message_sent: true });
      await goto(`/group/${$page.params.classId}/thread/${newThread.id}`);
    } catch (e) {
      $loading = false;
      form.callback({
        success: false,
        errorMessage: `Failed to create thread. Error: ${errorMessage(e, "Something went wrong while creating your conversation. If the issue persists, check <a class='underline' href='https://pingpong-hks.statuspage.io' target='_blank'>PingPong's status page</a> for updates.")}`,
        message_sent: false
      });
    }
  };

  let assistantDropdownOpen = false;
  // Set the new assistant selection.
  const selectAi = async (asst: Assistant) => {
    assistantDropdownOpen = false;
    await goto(`/group/${data.class.id}/?assistant=${asst.id}`);
  };
  const showModeratorsModal = () => {
    showModerators = true;
  };
</script>

<div class="flex justify-center relative grow bg-white">
  <div
    class="w-11/12 transition-opacity ease-in flex flex-col h-full justify-between"
    class:opacity-0={$loading}
  >
    {#if isConfigured}
      <Modal title="Group Moderators" bind:open={showModerators} autoclose outsideclose>
        <ModeratorsTable moderators={teachers} />
      </Modal>
      <div class="w-full h-full flex flex-col gap-4 items-center justify-center">
        <div class="flex flex-col items-center gap-2 lg:w-1/2 md:w-2/3 w-full text-center">
          <div
            class="mb-1 border rounded-full border-blue-light-30 p-2 bg-blue-light-50 w-16 h-16 flex items-center justify-center"
          >
            <Logo size={8} />
          </div>
          <div class="text-3xl font-medium">{assistant.name}</div>
          <div class="flex flex-row gap-1 text-gray-400 text-sm font-normal items-center">
            {#if assistantMeta.isCourseAssistant}
              <BadgeCheckOutline size="sm" />
              <span>Group assistant</span>
            {:else if assistantMeta.isMyAssistant}
              <UserOutline />
              <span>Created by you</span>
            {:else}
              <UsersOutline />
              <span>Created by {assistantMeta.creator}</span>
            {/if}
          </div>
          {#if assistant.description}
            <div class="text-gray-700 text-sm">{assistant.description}</div>
          {/if}
          {#if assistants.length > 1}
            <Button
              pill
              class={'flex flex-row py-1 px-3 gap-0.5 border border-gray-300 text-gray-600 text-xs hover:bg-gray-50 transition-all items-center' +
                (assistantDropdownOpen ? ' bg-gray-50' : '')}
              type="button"
            >
              <span class="text-xs font-normal text-center"> Change assistant </span>
              <ChevronSortOutline class="text-gray-500" size="xs" />
            </Button>
            <Dropdown
              class="p-3 h-full"
              classContainer="rounded-3xl lg:w-1/3 md:w-1/2 w-2/3 border border-gray-100 max-h-[40%] overflow-y-auto"
              bind:open={assistantDropdownOpen}
            >
              <!-- Show course assistants first -->
              {#if courseAssistants.length > 0}
                <DropdownItem
                  class="normal-case tracking-tight font-normal hover:bg-none pointer-events-none select-none text-gray-400 pb-1"
                >
                  Group assistants
                </DropdownItem>
              {/if}

              {#each courseAssistants as asst}
                <DropdownItem
                  on:click={() => selectAi(asst)}
                  on:touchstart={() => selectAi(asst)}
                  class="normal-case tracking-tight font-normal rounded rounded-lg hover:bg-gray-100 select-none max-w-full group"
                >
                  <div class="flex flex-row justify-between gap-5 max-w-full items-center">
                    <div class="flex flex-col gap-1 w-10/12">
                      <div class="text-sm leading-snug">
                        {#if asst.interaction_mode === 'voice'}
                          <MicrophoneOutline
                            size="sm"
                            class="inline align-text-bottom text-gray-400"
                          />
                          <Tooltip>Voice mode assistant</Tooltip>
                        {/if}
                        {asst.name}
                      </div>
                      {#if asst.description}
                        <div class="text-xs text-gray-500 truncate">
                          {asst.description}
                        </div>
                      {/if}
                    </div>

                    {#if assistant.id === asst.id}
                      <CheckCircleSolid size="md" class="text-blue-dark-40 group-hover:hidden" />
                    {/if}
                  </div>
                </DropdownItem>
              {/each}

              <!-- Show a divider if necessary -->
              {#if myAssistants.length > 0 && courseAssistants.length > 0}
                <DropdownDivider />
              {/if}

              <!-- Show the user's assistants -->
              {#if myAssistants.length > 0}
                <DropdownItem
                  class="normal-case tracking-tight font-normal hover:bg-none pointer-events-none select-none text-gray-400 pb-1"
                >
                  Your assistants
                </DropdownItem>

                {#each myAssistants as asst}
                  <DropdownItem
                    on:click={() => selectAi(asst)}
                    on:touchstart={() => selectAi(asst)}
                    class="normal-case tracking-tight font-normal rounded rounded-lg hover:bg-gray-100 select-none max-w-full group"
                  >
                    <div class="flex flex-row justify-between gap-5 max-w-full items-center">
                      <div class="flex flex-col gap-1 w-10/12">
                        <div class="text-sm leading-snug">
                          {#if asst.interaction_mode === 'voice'}
                            <MicrophoneOutline
                              size="sm"
                              class="inline align-text-bottom text-gray-400"
                            />
                            <Tooltip>Voice mode assistant</Tooltip>
                          {/if}
                          {asst.name}
                        </div>
                        {#if asst.description}
                          <div class="text-xs text-gray-500 truncate">
                            {asst.description}
                          </div>
                        {/if}
                      </div>

                      {#if assistant.id === asst.id}
                        <CheckCircleSolid size="md" class="text-blue-dark-40 group-hover:hidden" />
                      {/if}
                    </div>
                  </DropdownItem>
                {/each}
              {/if}
              <!-- Show a divider if necessary -->
              {#if otherAssistants.length > 0 && (myAssistants.length > 0 || courseAssistants.length > 0)}
                <DropdownDivider />
              {/if}

              <!-- Show the user's assistants -->
              {#if otherAssistants.length > 0}
                <DropdownItem
                  class="normal-case tracking-tight font-normal hover:bg-none pointer-events-none select-none text-gray-400 pb-1"
                >
                  Other assistants
                </DropdownItem>

                {#each otherAssistants as asst}
                  <DropdownItem
                    on:click={() => selectAi(asst)}
                    on:touchstart={() => selectAi(asst)}
                    class="normal-case tracking-tight font-normal rounded rounded-lg hover:bg-gray-100 select-none max-w-full group"
                  >
                    <div class="flex flex-row justify-between gap-5 max-w-full items-center">
                      <div class="flex flex-col gap-1 w-10/12">
                        <div class="text-sm leading-snug">
                          {#if asst.interaction_mode === 'voice'}
                            <MicrophoneOutline
                              size="sm"
                              class="inline align-text-bottom text-gray-400"
                            />
                            <Tooltip>Voice mode assistant</Tooltip>
                          {/if}
                          {asst.name}
                        </div>
                        {#if asst.description}
                          <div class="text-xs text-gray-500 truncate">
                            {asst.description}
                          </div>
                        {/if}
                      </div>

                      {#if assistant.id === asst.id}
                        <CheckCircleSolid size="md" class="text-blue-dark-40 group-hover:hidden" />
                      {/if}
                    </div>
                  </DropdownItem>
                {/each}
              {/if}
            </Dropdown>
          {/if}
        </div>
        {#if assistant.interaction_mode === 'voice'}
          <div class="h-[5%] max-h-8"></div>
          {#if $isFirefox}
            <div class="bg-blue-light-50 p-3 rounded-lg">
              <MicrophoneSlashOutline size="xl" class="text-blue-dark-40" />
            </div>
            <div class="flex flex-col items-center w-3/5">
              <p class="text-xl font-semibold text-blue-dark-40 text-center">
                Voice mode not available on Firefox
              </p>
              <p class="text-md font-base text-gray-600 text-center">
                We're working on bringing Voice mode to Firefox in a future update. For the best
                experience, please use Safari, Chrome, or Edge in the meantime.
              </p>
            </div>
          {:else}
            <div class="bg-blue-light-50 p-3 rounded-lg">
              <MicrophoneOutline size="xl" class="text-blue-dark-40" />
            </div>
            <div class="flex flex-col items-center min-w-2/5">
              <p class="text-xl font-semibold text-blue-dark-40 text-center">Voice mode</p>
              <p class="text-md font-base text-gray-600 text-center">
                Talk to this assistant using your voice.<br />Create a new session to begin.
              </p>
            </div>
            <div class="flex flex-row p-1.5">
              <Button
                class="flex flex-row py-1.5 px-4 gap-1.5 bg-blue-dark-40 text-white rounded rounded-lg text-xs hover:bg-blue-dark-50 hover:text-blue-light-50 transition-all"
                on:click={handleAudioThreadCreate}
                on:touchstart={handleAudioThreadCreate}
                type="button"
              >
                <CirclePlusSolid size="sm" />
                <span class="text-sm font-normal text-center"> Create session </span>
              </Button>
            </div>
          {/if}
        {:else if assistant.interaction_mode === 'chat' && !(assistant.assistant_should_message_first ?? false)}
          <div class="h-[8%] max-h-16"></div>
          {#if !isPrivate && assistantMeta.willDisplayUserInfo}
            <div
              class="flex flex-row gap-2 border border-red-600 px-3 py-1 items-stretch transition-all duration-200 rounded-2xl w-full lg:w-3/5 md:w-3/4"
            >
              <UsersSolid size="sm" class="text-red-600 pt-0" />
              <Span class="text-gray-700 text-xs font-normal"
                ><Button
                  class="p-0 text-gray-700 text-xs underline font-normal"
                  on:click={showModeratorsModal}
                  on:touchstart={showModeratorsModal}>Moderators</Button
                > have enabled a setting for this thread only that allows them to see
                <span class="font-semibold">your full name</span> and its content.</Span
              >
            </div>
          {/if}
          <div class="flex flex-col items-center w-full lg:w-3/5 md:w-3/4">
            <ChatInput
              mimeType={data.uploadInfo.mimeType}
              maxSize={data.uploadInfo.private_file_max_size}
              loading={$loading || !!$navigating}
              canSubmit={true}
              visionAcceptedFiles={supportsVision && allowVisionUpload
                ? data.uploadInfo.fileTypes({
                    file_search: false,
                    code_interpreter: false,
                    vision: true
                  })
                : null}
              {visionSupportOverride}
              {useImageDescriptions}
              fileSearchAcceptedFiles={supportsFileSearch
                ? data.uploadInfo.fileTypes({
                    file_search: true,
                    code_interpreter: false,
                    vision: false
                  })
                : null}
              codeInterpreterAcceptedFiles={supportsCodeInterpreter
                ? data.uploadInfo.fileTypes({
                    file_search: false,
                    code_interpreter: true,
                    vision: false
                  })
                : null}
              upload={handleUpload}
              remove={handleRemove}
              on:submit={handleSubmit}
            />
          </div>
        {:else if assistant.interaction_mode === 'chat' && (assistant.assistant_should_message_first ?? false)}
          <div class="h-[5%] max-h-8"></div>
          <div class="flex flex-col items-center min-w-2/5">
            <p class="text-md font-base text-gray-600 text-center">
              The assistant will send the first message.<br />Start a new conversation to begin.
            </p>
          </div>
          <div class="flex flex-row p-1.5">
            <Button
              class="flex flex-row py-1.5 px-4 gap-1.5 bg-blue-dark-40 text-white rounded rounded-lg text-xs hover:bg-blue-dark-50 hover:text-blue-light-50 transition-all"
              on:click={handleChatThreadCreate}
              on:touchstart={handleChatThreadCreate}
              type="button"
            >
              <PaperPlaneOutline size="sm" />
              <span class="text-sm font-normal text-center"> Start conversation </span>
            </Button>
          </div>
        {/if}
      </div>
      <div class="shrink-0 grow-0">
        <input type="hidden" name="assistant_id" bind:value={assistant.id} />
        <input type="hidden" name="parties" bind:value={parties} />
        <div class="my-3">
          {#if isPrivate}
            <div class="flex gap-2 items-start w-full text-sm flex-wrap lg:flex-nowrap">
              <LockSolid size="sm" class="text-orange pt-0" />
              <Span class="text-gray-600 text-xs font-normal"
                ><Button
                  class="p-0 text-gray-600 text-xs underline font-normal"
                  on:click={showModeratorsModal}
                  on:touchstart={showModeratorsModal}>Moderators</Button
                > <span class="font-semibold">cannot</span> see this thread or your name. For more
                information, please review
                <a href="/privacy-policy" rel="noopener noreferrer" class="underline"
                  >PingPong's privacy statement</a
                >. Assistants can make mistakes. Check important info.</Span
              >
            </div>
          {:else if assistantMeta.willDisplayUserInfo}
            {#if assistant.interaction_mode === 'voice'}
              <div class="flex gap-2 items-start w-full text-sm flex-wrap lg:flex-nowrap">
                <UsersSolid size="sm" class="text-orange pt-0" />
                <Span class="text-gray-600 text-xs font-normal"
                  ><Button
                    class="p-0 text-gray-600 text-xs underline font-normal"
                    on:click={showModeratorsModal}
                    on:touchstart={showModeratorsModal}>Moderators</Button
                  > can see this thread,
                  <span class="font-semibold"
                    >your full name, and listen to a recording of your conversation</span
                  >. For more information, please review
                  <a href="/privacy-policy" rel="noopener noreferrer" class="underline"
                    >PingPong's privacy statement</a
                  >. Assistants can make mistakes. Check important info.</Span
                >
              </div>
            {:else}
              <div class="flex gap-2 items-start w-full text-sm flex-wrap lg:flex-nowrap">
                <UsersSolid size="sm" class="text-orange pt-0" />
                <Span class="text-gray-600 text-xs font-normal"
                  ><Button
                    class="p-0 text-gray-600 text-xs underline font-normal"
                    on:click={showModeratorsModal}
                    on:touchstart={showModeratorsModal}>Moderators</Button
                  > can see this thread and <span class="font-semibold">your full name</span>. For
                  more information, please review
                  <a href="/privacy-policy" rel="noopener noreferrer" class="underline"
                    >PingPong's privacy statement</a
                  >. Assistants can make mistakes. Check important info.</Span
                >
              </div>
            {/if}
          {:else}
            <div class="flex gap-2 items-start w-full text-sm flex-wrap lg:flex-nowrap">
              <EyeSlashOutline size="sm" class="text-orange pt-0" />
              <Span class="text-gray-600 text-xs font-normal"
                ><Button
                  class="p-0 text-gray-600 text-xs underline font-normal"
                  on:click={showModeratorsModal}
                  on:touchstart={showModeratorsModal}>Moderators</Button
                > can see this thread but not your name. For more information, please review
                <a href="/privacy-policy" rel="noopener noreferrer" class="underline"
                  >PingPong's privacy statement</a
                >. Assistants can make mistakes. Check important info.</Span
              >
            </div>
          {/if}
        </div>
      </div>
    {:else}
      <div class="text-center m-auto">
        {#if !data.hasAssistants}
          <h1 class="text-2xl font-bold">No assistants configured.</h1>
        {:else if !data.hasAPIKey}
          <h1 class="text-2xl font-bold">No billing configured.</h1>
        {:else}
          <h1 class="text-2xl font-bold">Group is not configured.</h1>
        {/if}
      </div>
    {/if}
  </div>
</div>
