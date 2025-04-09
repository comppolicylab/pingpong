<script lang="ts">
  import { navigating, page } from '$app/stores';
  import { goto, invalidateAll, onNavigate } from '$app/navigation';
  import * as api from '$lib/api';
  import { happyToast, sadToast } from '$lib/toast';
  import { errorMessage } from '$lib/errors';
  import { blur } from 'svelte/transition';
  import {
    Accordion,
    AccordionItem,
    Avatar,
    Button,
    Card,
    Dropdown,
    DropdownItem,
    Modal,
    Span,
    Spinner
  } from 'flowbite-svelte';
  import { DoubleBounce } from 'svelte-loading-spinners';
  import Markdown from '$lib/components/Markdown.svelte';
  import Logo from '$lib/components/Logo.svelte';
  import ChatInput, { type ChatInputMessage } from '$lib/components/ChatInput.svelte';
  import {
    RefreshOutline,
    CodeOutline,
    ImageSolid,
    CogOutline,
    EyeOutline,
    EyeSlashOutline,
    LockSolid,
    MicrophoneOutline,
    ChevronSortOutline,
    PlaySolid,
    StopSolid,
    CheckOutline,
    MicrophoneSlashOutline
  } from 'flowbite-svelte-icons';
  import { parseTextContent } from '$lib/content';
  import { ThreadManager } from '$lib/stores/thread';
  import { ThreadManager as AudioThreadManager } from '$lib/stores/audioThread';
  import AttachmentDeletedPlaceholder from '$lib/components/AttachmentDeletedPlaceholder.svelte';
  import FilePlaceholder from '$lib/components/FilePlaceholder.svelte';
  import { writable } from 'svelte/store';
  import ModeratorsTable from '$lib/components/ModeratorsTable.svelte';
  import { base64ToArrayBuffer, WavRecorder, WavStreamPlayer } from '$lib/wavtools/index';
  import type { ExtendedMediaDeviceInfo } from '$lib/wavtools/lib/wav_recorder';
  import { isFirefox } from '$lib/stores/general';
  export let data;

  $: classId = parseInt($page.params.classId);
  $: threadId = parseInt($page.params.threadId);
  $: threadMgr =
    data.threadInteractionMode === 'voice'
      ? new AudioThreadManager(fetch, classId, threadId, data.threadData)
      : new ThreadManager(fetch, classId, threadId, data.threadData);
  $: isPrivate = data.class.private || false;
  $: teachers = data?.supervisors || [];
  $: canDeleteThread = data.canDeleteThread;
  $: canPublishThread = data.canPublishThread;
  $: canViewAssistant = data.canViewAssistant;
  $: messages = threadMgr.messages;
  $: participants = threadMgr.participants;
  $: published = threadMgr.published;
  $: error = threadMgr.error;
  $: threadManagerError = $error?.detail || null;
  $: assistantId = threadMgr.assistantId;
  $: isCurrentUser = $participants.user.includes('Me');
  let trashThreadFiles = writable<string[]>([]);
  $: threadAttachments = threadMgr.attachments;
  $: allFiles = Object.fromEntries(
    Object.entries($threadAttachments)
      .filter(([k, v]) => !$trashThreadFiles.includes(k))
      .map(([k, v]) => [
        k,
        {
          state: 'success',
          progress: 100,
          file: { type: v.content_type, name: v.name },
          response: v,
          promise: Promise.resolve(v)
        } as api.FileUploadInfo
      ])
  );
  $: fileSearchAcceptedFiles = supportsFileSearch
    ? data.uploadInfo.fileTypes({
        file_search: true,
        code_interpreter: false,
        vision: false
      })
    : null;
  $: codeInterpreterAcceptedFiles = supportsCodeInterpreter
    ? data.uploadInfo.fileTypes({
        file_search: false,
        code_interpreter: true,
        vision: false
      })
    : null;
  $: visionAcceptedFiles = supportsVision
    ? data.uploadInfo.fileTypes({
        file_search: false,
        code_interpreter: false,
        vision: true
      })
    : null;
  $: fileSearchAttachmentCount = Object.entries($threadAttachments).filter(
    ([k, v]) =>
      !$trashThreadFiles.includes(k) && (fileSearchAcceptedFiles ?? '').includes(v.content_type)
  ).length;
  $: codeInterpreterAttachmentCount = Object.entries($threadAttachments).filter(
    ([k, v]) =>
      !$trashThreadFiles.includes(k) &&
      (codeInterpreterAcceptedFiles ?? '').includes(v.content_type)
  ).length;

  let supportsVision = false;
  $: {
    const supportVisionModels = (data.models.filter((model) => model.supports_vision) || []).map(
      (model) => model.id
    );
    supportsVision = supportVisionModels.includes(data.threadModel);
  }
  let visionSupportOverride: boolean | undefined;
  $: {
    visionSupportOverride = data.models.find(
      (model) => model.id === data.threadModel
    )?.vision_support_override;
  }
  $: submitting = threadMgr.submitting;
  $: waiting = threadMgr.waiting;
  $: loading = threadMgr.loading;
  $: canFetchMore = threadMgr.canFetchMore;
  $: supportsFileSearch = data.availableTools.includes('file_search') || false;
  $: supportsCodeInterpreter = data.availableTools.includes('code_interpreter') || false;
  // TODO - should figure this out by checking grants instead of participants
  $: canSubmit = !!$participants.user && $participants.user.includes('Me');
  $: assistantDeleted = !$assistantId && $assistantId === 0;
  let useLatex = false;
  let useImageDescriptions = false;
  let assistantInteractionMode: 'voice' | 'chat' | null = null;
  $: {
    const assistant = data.assistants.find((assistant) => assistant.id === $assistantId);
    if (assistant) {
      useLatex = assistant.use_latex || false;
      useImageDescriptions = assistant.use_image_descriptions || false;
      assistantInteractionMode = assistant.interaction_mode;
    } else {
      console.warn(`Definition for assistant ${$assistantId} not found.`);
    }
  }
  let showModerators = false;

  let currentMessageAttachments: api.ServerFile[] = [];
  // Get the name of the participant in the chat thread.
  const getName = (message: api.OpenAIMessage) => {
    if (message.role === 'user') {
      if (message?.metadata?.is_current_user) {
        return data?.me?.user?.name || data?.me?.user?.email || 'Anonymous User';
      }
      return (message?.metadata?.name as string | undefined) || 'Anonymous User';
    } else {
      // Note that we need to distinguish between unknown and deleted assistants.
      if ($assistantId !== null) {
        return $participants.assistant[$assistantId] || 'PingPong Bot';
      }
      return 'PingPong Bot';
    }
  };

  export function processString(dirty_string: string): {
    clean_string: string;
    images: api.ImageProxy[];
  } {
    const jsonPattern = /\{"Rd1IFKf5dl"\s*:\s*\[.*?\]\}/s;
    const match = dirty_string.match(jsonPattern);

    let clean_string = dirty_string;
    let images: api.ImageProxy[] = [];

    if (match) {
      try {
        const user_images = JSON.parse(match[0]);
        images = user_images['Rd1IFKf5dl'] || [];
        clean_string = dirty_string.replace(jsonPattern, '').trim();
      } catch (error) {
        console.error('Failed to parse user images JSON:', error);
      }
    }

    return { clean_string, images };
  }

  const convertImageProxyToInfo = (data: api.ImageProxy[]) => {
    return data.map((image) => {
      const imageAsServerFile = {
        file_id: image.complements ?? '',
        content_type: image.content_type,
        name: image.name
      } as api.ServerFile;
      return {
        state: 'success',
        progress: 100,
        file: { type: image.content_type, name: image.name },
        response: imageAsServerFile,
        promise: Promise.resolve(imageAsServerFile)
      } as api.FileUploadInfo;
    });
  };

  // Get the avatar URL of the participant in the chat thread.
  const getImage = (message: api.OpenAIMessage) => {
    if (message.role === 'user') {
      if (message?.metadata?.is_current_user) {
        return data?.me?.profile?.image_url || '';
      }
      return '';
    }
    // TODO - custom image for the assistant

    return '';
  };

  // Scroll to the bottom of the chat thread.
  const scroll = (el: HTMLDivElement, messageList: unknown[]) => {
    // Scroll to the bottom of the element.
    el.scrollTo({
      top: el.scrollHeight,
      behavior: 'smooth'
    });
    return {
      // TODO - would be good to figure out how to do this without a timeout.
      update: () => {
        setTimeout(() => {
          // Don't auto-scroll if the user is not near the bottom of the chat.
          // TODO - we can show an indicator if there are new messages that we'd want to scroll to.
          if (el.scrollTop + el.clientHeight < el.scrollHeight - 600) {
            return;
          }

          el.scrollTo({
            top: el.scrollHeight,
            behavior: 'smooth'
          });
        }, 250);
      }
    };
  };

  // Fetch an earlier page of messages
  const fetchMoreMessages = async () => {
    await threadMgr.fetchMore();
  };

  // Fetch a singular code interpreter step result
  const fetchCodeInterpreterResult = async (content: api.Content) => {
    if (content.type !== 'code_interpreter_call_placeholder') {
      sadToast('Invalid code interpreter request.');
      return;
    }
    try {
      await threadMgr.fetchCodeInterpreterResult(
        content.thread_id,
        content.run_id,
        content.step_id
      );
    } catch (e) {
      sadToast(
        `Failed to load code interpreter results. Error: ${errorMessage(e, "We're facing an unknown error. Check PingPong's status page for updates if this persists.")}`
      );
    }
  };

  // Handle sending a message
  const postMessage = async ({
    message,
    code_interpreter_file_ids,
    file_search_file_ids,
    vision_file_ids,
    visionFileImageDescriptions,
    callback
  }: ChatInputMessage) => {
    try {
      await threadMgr.postMessage(
        data.me.user!.id,
        message,
        callback,
        code_interpreter_file_ids,
        file_search_file_ids,
        vision_file_ids,
        visionFileImageDescriptions,
        currentMessageAttachments
      );
    } catch (e) {
      callback({
        success: false,
        errorMessage: `Failed to send message. Error: ${errorMessage(e, "Something went wrong while sending your message. If the issue persists, check <a class='underline' href='https://pingpong-hks.statuspage.io' target='_blank'>PingPong's status page</a> for updates.")}`,
        message_sent: false
      });
    }
  };

  // Handle submit on the chat input
  const handleSubmit = async (e: CustomEvent<ChatInputMessage>) => {
    await postMessage(e.detail);
  };

  // Handle file upload
  const handleUpload = (
    f: File,
    onProgress: (p: number) => void,
    purpose: api.FileUploadPurpose = 'assistants',
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
    if (result.$status >= 300) {
      sadToast(`Failed to delete file. Error: ${result.detail || 'unknown error'}`);
      throw new Error(result.detail || 'unknown error');
    }
  };

  const handleDismissError = () => {
    threadMgr.dismissError();
  };

  /**
   * Publish or unpublish a thread.
   */
  const togglePublish = async () => {
    if (!threadMgr.thread) {
      return;
    }
    let verb = 'publish';
    try {
      if (threadMgr.thread.private) {
        await threadMgr.publish();
      } else {
        verb = 'unpublish';
        await threadMgr.unpublish();
      }
      invalidateAll();
    } catch (e) {
      sadToast(
        `Failed to ${verb} thread. Error: ${errorMessage(e, "We're facing an unknown error. Check PingPong's status page for updates if this persists.")}`
      );
    }
  };

  /**
   * Delete the thread.
   */
  const deleteThread = async () => {
    if (!threadMgr.thread) {
      return;
    }
    try {
      if (!confirm('Are you sure you want to delete this thread? This cannot be undone!')) {
        return;
      }
      await threadMgr.delete();
      happyToast('Thread deleted.');
      await goto(`/group/${classId}`, { invalidateAll: true });
    } catch (e) {
      sadToast(
        `Failed to delete thread. Error: ${errorMessage(e, "We're facing an unknown error. Check PingPong's status page for updates if this persists.")}`
      );
    }
  };

  let wavRecorder: WavRecorder | null = null;
  let wavStreamPlayer: WavStreamPlayer | null = null;
  let microphoneAccess = false;
  let audioDevices: ExtendedMediaDeviceInfo[] = [];
  let selectedAudioDevice: ExtendedMediaDeviceInfo | null = null;
  let openMicrophoneModal = false;

  /**
   * Select an audio device. If no device ID is provided, the first available device will be selected.
   * @param deviceId Optional ID of the audio device to select.
   */
  const selectAudioDevice = (deviceId?: string) => {
    const lookupDeviceId = deviceId || selectedAudioDevice?.deviceId;
    if (lookupDeviceId) {
      selectedAudioDevice =
        audioDevices.find((device) => device.deviceId === lookupDeviceId) || null;
    }

    // Check if any device is default based on ExtendedMediaDeviceInfo
    if (audioDevices.length > 0) {
      const defaultDevice = audioDevices.find((device) => device.default);
      if (defaultDevice) {
        selectedAudioDevice = defaultDevice;
      }
    }

    // If no device is selected, select the first available device
    if (!selectedAudioDevice) {
      selectedAudioDevice = audioDevices[0] || null;
    }
  };

  /**
   * Handle changes in the list of available audio devices.
   * This function updates the list of audio devices and selects a default device.
   * @param devices The updated list of available audio devices.
   */
  const handleDeviceChange = (devices: ExtendedMediaDeviceInfo[]) => {
    audioDevices = devices;
    selectAudioDevice();
  };

  /**
   * Handle the setup of a session.
   * This function initializes the WavRecorder and updates available audio devices.
   * The user will be asked to allow microphone access.
   */
  const handleSessionSetup = async () => {
    wavRecorder = new WavRecorder({ sampleRate: 24000, debug: true });
    wavStreamPlayer = new WavStreamPlayer({ sampleRate: 24000 });
    try {
      await wavStreamPlayer.connect();
    } catch (error) {
      sadToast(
        `Failed to set up audio output to your speakers. Error: ${errorMessage(error, "We're facing an unknown error. Check PingPong's status page for updates if this persists.")}`
      );
      wavRecorder.quit();
      wavRecorder = null;
      wavStreamPlayer = null;
      return;
    }
    try {
      audioDevices = await wavRecorder.listDevices();
      wavRecorder.listenForDeviceChange(handleDeviceChange);
      microphoneAccess = true;
    } catch (error) {
      sadToast(
        `Failed to access microphone. Error: ${errorMessage(error, "We're facing an unknown error. Check PingPong's status page for updates if this persists.")}`
      );
      wavRecorder.quit();
      wavRecorder = null;
      wavStreamPlayer = null;
      return;
    }

    // handleDeviceChange is called when set
    // when listenForDeviceChange is called,
    // but just in case
    if (!selectedAudioDevice) {
      selectAudioDevice();
    }
  };

  let socket: WebSocket | null = null;
  let startingAudioSession = false;
  let audioSessionStarted = false;

  /**
   * Process audio chunks.
   * This function sends the audio data to the server via WebSocket.
   * @param data The audio data to be processed.
   * @param data.raw The raw audio data.
   * @param data.mono The mono audio data.
   */
  const chunkProcessor = (data: { raw: ArrayBuffer; mono: ArrayBuffer }) => {
    if (!socket || !audioSessionStarted) {
      return;
    }
    socket.send(data.mono);
  };

  /**
   * Reset the audio session.
   * This function closes the WebSocket connection and resets the state of the audio session.
   */
  const resetAudioSession = async () => {
    if (socket) {
      socket.close();
      socket = null;
    }
    startingAudioSession = false;
    audioSessionStarted = false;
    openMicrophoneModal = false;
    microphoneAccess = false;
    audioDevices = [];
    selectedAudioDevice = null;
    if (wavRecorder) {
      await wavRecorder.quit();
      wavRecorder = null;
    }
    if (wavStreamPlayer) {
      await wavStreamPlayer.interrupt();
      wavStreamPlayer = null;
    }
  };

  /**
   * Handle the start of a session.
   */
  const handleSessionStart = async () => {
    if (startingAudioSession) {
      return;
    }
    startingAudioSession = true;
    if (!wavRecorder) {
      sadToast('We failed to start the session. Please try again.');
      return;
    }
    if (!selectedAudioDevice) {
      sadToast('No audio device selected. Please select a microphone.');
      return;
    }
    if (!wavStreamPlayer) {
      sadToast('Failed to set up audio output to your speakers.');
      return;
    }

    socket = api.createAudioWebsocket(classId, threadId);
    socket.binaryType = 'arraybuffer';

    socket.addEventListener('message', async (event) => {
      const message = JSON.parse(event.data);
      switch (message.type) {
        case 'session.updated':
          if (!wavRecorder) {
            sadToast('We failed to start the session. Please try again.');
            return;
          }
          if (!selectedAudioDevice) {
            sadToast('No audio device selected. Please select a microphone.');
            return;
          }
          await wavRecorder.begin(selectedAudioDevice.deviceId);
          await wavRecorder.record(chunkProcessor);
          startingAudioSession = false;
          audioSessionStarted = true;
          break;
        case 'input_audio_buffer.speech_started':
          if (!wavStreamPlayer) {
            sadToast('Failed to set up audio output to your speakers.');
            return;
          }
          await wavStreamPlayer.interrupt();
          // TODO: Inform the server that we've stopped playing the audio.
          // const trackSampleOffset = await wavStreamPlayer.interrupt();
          // if (trackSampleOffset?.trackId) {
          //   const { trackId, offset } = trackSampleOffset;
          // }
          break;
        case 'response.audio.delta':
          if (!wavStreamPlayer) {
            sadToast('Failed to set up audio output to your speakers.');
            return;
          }
          wavStreamPlayer.add16BitPCM(base64ToArrayBuffer(message.audio), message.item_id);
          break;
        case 'error':
          if (message.error.type === 'invalid_request_error') {
            sadToast(
              `Failed to start session. Error: ${errorMessage(message.error.message, "We're facing an unknown error. Check PingPong's status page for updates if this persists.")}`
            );
            await resetAudioSession();
          } else {
            sadToast(
              `We faced an error. Error: ${errorMessage(
                message.error.message,
                "We're facing an unknown error. Check PingPong's status page for updates if this persists."
              )}`
            );
          }
          break;
        default:
          console.warn('Unknown message type:', message.type);
      }
    });
  };

  let endingAudioSession = false;
  /**
   * Handle session end.
   */
  const handleSessionEnd = async () => {
    if (endingAudioSession) {
      return;
    }
    endingAudioSession = true;
    if (socket) {
      socket.close();
      socket = null;
    }
    audioDevices = [];
    selectedAudioDevice = null;
    if (wavRecorder) {
      await wavRecorder.quit();
      wavRecorder = null;
    }
    if (wavStreamPlayer) {
      await wavStreamPlayer.interrupt();
      wavStreamPlayer = null;
    }
    await invalidateAll();
    startingAudioSession = false;
    audioSessionStarted = false;
    openMicrophoneModal = false;
    microphoneAccess = false;
    endingAudioSession = false;
  };

  /*
   * Delete a file from the thread.
   */
  const removeFile = async (evt: CustomEvent<api.FileUploadInfo>) => {
    const file = evt.detail;
    if (file.state === 'deleting' || !(file.response && 'file_id' in file.response)) {
      return;
    } else {
      allFiles[(file.response as api.ServerFile).file_id].state = 'deleting';
      const result = await api.deleteThreadFile(
        fetch,
        data.class.id,
        threadId,
        (file.response as api.ServerFile).file_id
      );
      if (result.$status >= 300) {
        allFiles[(file.response as api.ServerFile).file_id].state = 'success';
        sadToast(`Failed to delete file: ${result.detail || 'unknown error'}`);
      } else {
        trashThreadFiles.update((files) => [...files, (file.response as api.ServerFile).file_id]);
        happyToast('Thread file successfully deleted.');
      }
    }
  };

  const showModeratorsModal = () => {
    showModerators = true;
  };

  onNavigate(async () => {
    await resetAudioSession();
  });
</script>

<div class="w-full flex flex-col justify-between grow min-h-0 relative">
  <div class="overflow-y-auto pb-4 px-2 lg:px-4" use:scroll={$messages}>
    {#if $canFetchMore}
      <div class="flex justify-center grow">
        <Button size="sm" class="text-sky-600 hover:text-sky-800" on:click={fetchMoreMessages}>
          <RefreshOutline class="w-3 h-3 me-2" /> Load earlier messages ...
        </Button>
      </div>
    {/if}
    {#each $messages as message}
      {@const attachment_file_ids = message.data.attachments
        ? new Set(message.data.attachments.map((attachment) => attachment.file_id))
        : []}
      <div class="py-4 px-6 flex gap-x-3">
        <div class="shrink-0">
          {#if message.data.role === 'user'}
            <Avatar size="sm" src={getImage(message.data)} />
          {:else}
            <Logo size={8} />
          {/if}
        </div>
        <div class="max-w-full w-full">
          <div class="font-semibold text-blue-dark-40 mb-2 mt-1">{getName(message.data)}</div>
          {#each message.data.content as content}
            {#if content.type === 'text'}
              {@const { clean_string, images } = processString(content.text.value)}
              {@const imageInfo = convertImageProxyToInfo(images)}

              <div class="leading-6">
                <Markdown
                  content={parseTextContent(
                    { value: clean_string, annotations: content.text.annotations },
                    api.fullPath(`/class/${classId}/thread/${threadId}`)
                  )}
                  syntax={true}
                  latex={useLatex}
                />
              </div>
              {#if attachment_file_ids}
                <div class="flex flex-wrap gap-2">
                  {#each attachment_file_ids as file_id}
                    {#if allFiles[file_id]}
                      <FilePlaceholder
                        info={allFiles[file_id]}
                        mimeType={data.uploadInfo.mimeType}
                        on:delete={removeFile}
                      />
                    {:else}
                      <AttachmentDeletedPlaceholder {file_id} />
                    {/if}
                  {/each}
                  {#each imageInfo as image}
                    {#if !(image.response && 'file_id' in image.response && image.response.file_id in allFiles)}
                      <FilePlaceholder
                        info={image}
                        purpose="vision"
                        mimeType={data.uploadInfo.mimeType}
                        preventDeletion={true}
                        on:delete={() => {}}
                      />
                    {/if}
                  {/each}
                </div>
              {/if}
            {:else if content.type === 'code'}
              <div class="leading-6 w-full">
                <Accordion flush>
                  <AccordionItem>
                    <span slot="header"
                      ><div class="flex-row flex items-center space-x-2">
                        <div><CodeOutline size="lg" /></div>
                        <div>Code Interpreter</div>
                      </div></span
                    >
                    <pre style="white-space: pre-wrap;" class="text-black">{content.code}</pre>
                  </AccordionItem>
                </Accordion>
              </div>
            {:else if content.type === 'code_interpreter_call_placeholder'}
              <Card padding="md" class="max-w-full flex-row flex items-center justify-between">
                <div class="flex-row flex items-center space-x-2">
                  <div><CodeOutline size="lg" /></div>
                  <div>Code Interpreter</div>
                </div>

                <div class="flex flex-wrap items-center gap-2">
                  <Button
                    outline
                    disabled={$loading || $submitting || $waiting}
                    pill
                    size="xs"
                    color="alternative"
                    on:click={() => fetchCodeInterpreterResult(content)}
                    on:touchstart={() => fetchCodeInterpreterResult(content)}
                  >
                    Load Code Interpreter Results
                  </Button>
                </div></Card
              >
            {:else if content.type === 'code_output_image_file'}
              <Accordion flush>
                <AccordionItem>
                  <span slot="header"
                    ><div class="flex-row flex items-center space-x-2">
                      <div><ImageSolid size="lg" /></div>
                      <div>Code Interpreter Output</div>
                    </div></span
                  >
                  <div class="leading-6 w-full">
                    <img
                      class="img-attachment m-auto"
                      src={api.fullPath(
                        `/class/${classId}/thread/${threadId}/image/${content.image_file.file_id}`
                      )}
                      alt="Attachment generated by the assistant"
                    />
                  </div>
                </AccordionItem>
              </Accordion>
            {:else if content.type === 'image_file'}
              <div class="leading-6 w-full">
                <img
                  class="img-attachment m-auto"
                  src={api.fullPath(
                    `/class/${classId}/thread/${threadId}/image/${content.image_file.file_id}`
                  )}
                  alt="Attachment generated by the assistant"
                />
              </div>
            {:else}
              <div class="leading-6"><pre>{JSON.stringify(content, null, 2)}</pre></div>
            {/if}
          {/each}
        </div>
      </div>
    {/each}
  </div>
  <Modal title="Group Moderators" bind:open={showModerators} autoclose outsideclose
    ><ModeratorsTable moderators={teachers} /></Modal
  >
  {#if !$loading}
    {#if data.threadInteractionMode === 'voice' && !microphoneAccess && $messages.length === 0 && assistantInteractionMode === 'voice'}
      {#if $isFirefox}
        <div class="w-full h-full flex flex-col gap-4 items-center justify-center">
          <div class="bg-blue-light-50 p-3 rounded-lg">
            <MicrophoneSlashOutline size="xl" class="text-blue-dark-40" />
          </div>
          <div class="flex flex-col items-center w-2/5">
            <p class="text-xl font-semibold text-blue-dark-40 text-center">
              Voice mode not available on Firefox
            </p>
            <p class="text-md font-base text-gray-600 text-center">
              We're working on bringing Voice mode to Firefox in a future update. For the best
              experience, please use Safari, Chrome, or Edge in the meantime.
            </p>
          </div>
        </div>
      {:else}
        <div class="w-full h-full flex flex-col gap-4 items-center justify-center">
          <div class="bg-blue-light-50 p-3 rounded-lg">
            <MicrophoneOutline size="xl" class="text-blue-dark-40" />
          </div>
          <div class="flex flex-col items-center w-2/5">
            <p class="text-xl font-semibold text-blue-dark-40 text-center">Voice mode</p>
            <p class="text-md font-base text-gray-600 text-center">
              To get started, enable microphone access.
            </p>
          </div>
          <Button
            class="flex flex-row py-1.5 px-4 gap-1.5 bg-blue-dark-40 text-white rounded rounded-lg text-xs hover:bg-blue-dark-50 hover:text-blue-light-50 transition-all text-sm font-normal text-center"
            type="button"
            on:click={handleSessionSetup}
            on:touchstart={handleSessionSetup}
          >
            Enable access
          </Button>
        </div>
      {/if}
    {:else if data.threadInteractionMode === 'voice' && microphoneAccess && $messages.length === 0 && assistantInteractionMode === 'voice'}
      {#if $isFirefox}
        <div class="w-full h-full flex flex-col gap-4 items-center justify-center">
          <div class="bg-blue-light-50 p-3 rounded-lg">
            <MicrophoneSlashOutline size="xl" class="text-blue-dark-40" />
          </div>
          <div class="flex flex-col items-center w-2/5">
            <p class="text-xl font-semibold text-blue-dark-40 text-center">
              Voice mode not available on Firefox
            </p>
            <p class="text-md font-base text-gray-600 text-center">
              We're working on bringing Voice mode to Firefox in a future update. For the best
              experience, please use Safari, Chrome, or Edge in the meantime.
            </p>
          </div>
        </div>
      {:else}
        <div class="w-full h-full flex flex-col gap-4 items-center justify-center">
          <div class="bg-blue-light-50 p-3 rounded-lg">
            <MicrophoneOutline size="xl" class="text-blue-dark-40" />
          </div>
          <div class="flex flex-col items-center w-2/5">
            <p class="text-xl font-semibold text-blue-dark-40 text-center">Voice mode</p>
            {#if endingAudioSession}
              <p class="text-md font-base text-gray-600 text-center">
                Finishing up your session...
              </p>
            {:else}
              <p class="text-md font-base text-gray-600 text-center">
                When you're ready, start the session to begin recording.
              </p>
            {/if}
          </div>
          <div class="w-full flex justify-center">
            <div
              class="bg-gray-100 flex flex-row gap-2 items-center justify-center shadow-xl rounded-xl px-2 py-1.5 w-fit h-fit"
            >
              {#if !audioSessionStarted}
                <Button
                  class="flex flex-row gap-1 bg-blue-dark-40 text-white rounded rounded-lg text-xs hover:bg-blue-dark-50 transition-all text-sm font-normal text-center px-3 py-2"
                  type="button"
                  on:click={handleSessionStart}
                  on:touchstart={handleSessionStart}
                  disabled={!microphoneAccess}
                >
                  {#if startingAudioSession}
                    <Spinner color="custom" customColor="fill-white" class="w-4 h-4 mr-1" />
                  {:else}
                    <PlaySolid class="pl-0 ml-0" size="md" />
                  {/if}
                  <span class="mr-1">Start session</span>
                </Button>
              {:else}
                <Button
                  class="flex flex-row gap-1 bg-amber-700 text-white rounded rounded-lg text-xs hover:bg-amber-800 transition-all text-sm font-normal text-center px-3 py-2"
                  type="button"
                  on:click={handleSessionEnd}
                  on:touchstart={handleSessionEnd}
                  disabled={!microphoneAccess}
                >
                  {#if endingAudioSession}
                    <Spinner color="custom" customColor="fill-white" class="w-4 h-4 mr-1" />
                  {:else}
                    <StopSolid class="pl-0 ml-0" size="md" />
                  {/if}
                  <span class="mr-1">End session</span>
                </Button>
              {/if}
              <Button
                id="top-dd"
                class="flex flex-row gap-2 min-w-56 max-w-56 hover:bg-gray-300 px-3 py-2 grow-0 shrink-0 transition-all text-sm font-normal justify-between text-gray-800 rounded-lg"
                disabled={!microphoneAccess ||
                  audioSessionStarted ||
                  startingAudioSession ||
                  endingAudioSession}
              >
                <div class="flex flex-row gap-2 justify-start w-5/6">
                  <MicrophoneOutline class="w-5 h-5" />
                  <span class="truncate"
                    >{selectedAudioDevice?.label || 'Select microphone...'}</span
                  >
                </div>
                <ChevronSortOutline class="ml-2 w-4 h-4" strokeWidth="2" /></Button
              >
              {#if audioDevices.length === 0}
                <Dropdown placement="top" triggeredBy="#top-dd" bind:open={openMicrophoneModal}>
                  <DropdownItem class="flex flex-row gap-2 items-center">
                    <span>No microphones available</span>
                  </DropdownItem>
                </Dropdown>
              {:else}
                <Dropdown placement="top" triggeredBy="#top-dd" bind:open={openMicrophoneModal}>
                  {#each audioDevices as audioDevice}
                    <DropdownItem
                      class="flex flex-row gap-2 items-center"
                      on:click={() => {
                        selectAudioDevice(audioDevice.deviceId);
                        openMicrophoneModal = false;
                      }}
                    >
                      {#if audioDevice.deviceId === selectedAudioDevice?.deviceId}
                        <CheckOutline class="w-5 h-5" />
                      {:else}
                        <span class="w-5 h-5"></span>
                      {/if}
                      <span>{audioDevice.label}</span>
                    </DropdownItem>
                  {/each}
                </Dropdown>
              {/if}
            </div>
          </div>
        </div>
      {/if}
    {/if}

    <div class="w-full bg-gradient-to-t from-white to-transparent">
      <div class="w-11/12 mx-auto relative flex flex-col">
        {#if data.threadInteractionMode == 'chat' && assistantInteractionMode === 'chat'}
          {#if $waiting || $submitting}
            <div
              class="w-full flex justify-center absolute -top-10"
              transition:blur={{ amount: 10 }}
            >
              <DoubleBounce color="#0ea5e9" size="30" />
            </div>
          {/if}
          <ChatInput
            mimeType={data.uploadInfo.mimeType}
            maxSize={data.uploadInfo.private_file_max_size}
            bind:attachments={currentMessageAttachments}
            {threadManagerError}
            {visionAcceptedFiles}
            {fileSearchAcceptedFiles}
            {codeInterpreterAcceptedFiles}
            {visionSupportOverride}
            {useImageDescriptions}
            {assistantDeleted}
            {canViewAssistant}
            canSubmit={canSubmit && !assistantDeleted && canViewAssistant}
            disabled={!canSubmit || assistantDeleted || !!$navigating || !canViewAssistant}
            loading={$submitting || $waiting}
            {fileSearchAttachmentCount}
            {codeInterpreterAttachmentCount}
            upload={handleUpload}
            remove={handleRemove}
            on:submit={handleSubmit}
            on:dismissError={handleDismissError}
          />
        {:else if data.threadInteractionMode === 'voice' && ($messages.length > 0 || assistantInteractionMode === 'chat')}
          <div
            class="flex flex-col bg-seasalt gap-2 border border-melon pl-4 py-2.5 pr-3 items-stretch transition-all duration-200 relative shadow-[0_0.25rem_1.25rem_rgba(254,184,175,0.15)] focus-within:shadow-[0_0.25rem_1.25rem_rgba(253,148,134,0.25)] hover:border-coral-pink focus-within:border-coral-pink z-20 rounded-2xl"
          >
            <div class="flex flex-row gap-2">
              <MicrophoneOutline class="w-6 h-6 text-gray-700" />
              <div class="flex flex-col">
                <span class="font-semibold text-md text-gray-700">Voice Mode Session</span><span
                  class="font-normal text-md text-gray-700"
                  >This conversation was completed in Voice mode and is read-only. To continue
                  chatting, start a new conversation.</span
                >
              </div>
            </div>
          </div>
        {:else if data.threadInteractionMode === 'chat' && assistantInteractionMode === 'voice'}
          <div
            class="flex flex-col bg-seasalt gap-2 border border-melon pl-4 py-2.5 pr-3 items-stretch transition-all duration-200 relative shadow-[0_0.25rem_1.25rem_rgba(254,184,175,0.15)] focus-within:shadow-[0_0.25rem_1.25rem_rgba(253,148,134,0.25)] hover:border-coral-pink focus-within:border-coral-pink z-20 rounded-2xl"
          >
            <div class="flex flex-row gap-2">
              <MicrophoneOutline class="w-6 h-6 text-gray-700" />
              <div class="flex flex-col">
                <span class="font-semibold text-md text-gray-700">Assistant in Voice mode</span
                ><span class="font-normal text-md text-gray-700"
                  >This assistant uses audio. Start a new session to keep the conversation going.</span
                >
              </div>
            </div>
          </div>
        {/if}
        <div class="flex gap-2 items-center w-full text-sm justify-between grow my-3">
          <div class="flex gap-2 grow shrink min-w-0">
            {#if !$published && isPrivate}
              <LockSolid size="sm" class="text-orange" />
              <Span class="text-gray-600 text-xs font-normal"
                ><Button
                  class="p-0 text-gray-600 text-xs underline font-normal"
                  on:click={showModeratorsModal}
                  on:touchstart={showModeratorsModal}>Moderators</Button
                > <span class="font-semibold">cannot</span> see this thread or your name. {#if isCurrentUser}For
                  more information, please review <a
                    href="/privacy-policy"
                    rel="noopener noreferrer"
                    class="underline">PingPong's privacy statement</a
                  >.
                {/if}Assistants can make mistakes. Check important info.</Span
              >
            {:else if !$published}
              <EyeSlashOutline size="sm" class="text-orange" />
              <Span class="text-gray-600 text-xs font-normal"
                ><Button
                  class="p-0 text-gray-600 text-xs underline font-normal"
                  on:click={showModeratorsModal}
                  on:touchstart={showModeratorsModal}>Moderators</Button
                > can see this thread but not {isCurrentUser ? 'your' : "the user's"} name.
                {#if isCurrentUser}For more information, please review <a
                    href="/privacy-policy"
                    rel="noopener noreferrer"
                    class="underline">PingPong's privacy statement</a
                  >.
                {/if}Assistants can make mistakes. Check important info.</Span
              >
            {:else}
              <EyeOutline size="sm" class="text-orange" />
              <Span class="text-gray-600 text-xs font-normal"
                >Everyone in this group can see this thread but not {isCurrentUser
                  ? 'your'
                  : "the user's"} name. Assistants can make mistakes. Check important info.</Span
              >
            {/if}
          </div>

          {#if !(data.threadInteractionMode === 'voice' && $messages.length === 0 && assistantInteractionMode === 'voice')}
            <div class="shrink-0 grow-0 h-auto">
              <CogOutline class="dark:text-white cursor-pointer w-6 h-4 font-light" size="lg" />
              <Dropdown>
                <DropdownItem on:click={togglePublish} disabled={!canPublishThread}>
                  <span class:text-gray-300={!canPublishThread}>
                    {#if $published}
                      Unpublish
                    {:else}
                      Publish
                    {/if}
                  </span>
                </DropdownItem>
                <DropdownItem on:click={deleteThread} disabled={!canDeleteThread}>
                  <span class:text-gray-300={!canDeleteThread}>Delete</span>
                </DropdownItem>
              </Dropdown>
            </div>
          {/if}
        </div>
      </div>
    </div>
  {/if}
</div>

<style lang="css">
  .img-attachment {
    max-width: min(95%, 700px);
  }
</style>
