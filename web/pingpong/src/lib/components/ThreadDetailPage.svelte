<script lang="ts">
  import { navigating, page } from '$app/stores';
  import { beforeNavigate, goto, invalidateAll, onNavigate } from '$app/navigation';
  import * as api from '$lib/api';
  import { happyToast, sadToast } from '$lib/toast';
  import { errorMessage } from '$lib/errors';
  import { computeLatestIncidentTimestamps, filterLatestIncidentUpdates } from '$lib/statusUpdates';
  import { blur } from 'svelte/transition';
  import {
    Accordion,
    AccordionItem,
    Avatar,
    Button,
    Card,
    Dropdown,
    DropdownDivider,
    DropdownItem,
    Modal,
    Span,
    Spinner,
    Tooltip
  } from 'flowbite-svelte';
  import { DoubleBounce } from 'svelte-loading-spinners';
  import Markdown from '$lib/components/Markdown.svelte';
  import Logo from '$lib/components/Logo.svelte';
  import ChatInput, { type ChatInputMessage } from '$lib/components/ChatInput.svelte';
  import AssistantVersionBadge from '$lib/components/AssistantVersionBadge.svelte';
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
    MicrophoneSlashOutline,
    UsersSolid,
    LinkOutline,
    TerminalOutline
  } from 'flowbite-svelte-icons';
  import { parseTextContent } from '$lib/content';
  import { ThreadManager } from '$lib/stores/thread';
  import AttachmentDeletedPlaceholder from '$lib/components/AttachmentDeletedPlaceholder.svelte';
  import FilePlaceholder from '$lib/components/FilePlaceholder.svelte';
  import { writable } from 'svelte/store';
  import ModeratorsTable from '$lib/components/ModeratorsTable.svelte';
  import { base64ToArrayBuffer, WavRecorder, WavStreamPlayer } from '$lib/wavtools/index';
  import type { ExtendedMediaDeviceInfo } from '$lib/wavtools/lib/wav_recorder';
  import { isFirefox } from '$lib/stores/general';
  import Sanitize from '$lib/components/Sanitize.svelte';
  import AudioPlayer from '$lib/components/AudioPlayer.svelte';
  import { tick } from 'svelte';
  import FileCitation from './FileCitation.svelte';
  import StatusErrors from './StatusErrors.svelte';
  export let data;

  let userTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  $: classId = parseInt($page.params.classId);
  $: threadId = parseInt($page.params.threadId);
  $: threadMgr = new ThreadManager(
    fetch,
    classId,
    threadId,
    data.threadData,
    data.threadInteractionMode || 'chat',
    userTimezone
  );
  $: isPrivate = data.class?.private || false;
  $: isAnonymousSession = data?.me?.status === 'anonymous';
  $: teachers = data?.supervisors || [];
  $: canDeleteThread = data.canDeleteThread;
  $: canPublishThread = data.canPublishThread;
  $: canViewAssistant = data.canViewAssistant;
  $: messages = threadMgr.messages;
  $: participants = threadMgr.participants;
  $: published = threadMgr.published;
  $: version = threadMgr.version;
  $: error = threadMgr.error;
  $: threadManagerError = $error?.detail || null;
  $: assistantId = threadMgr.assistantId;
  $: isCurrentUser = $participants.user.includes('Me');
  $: threadInstructions = threadMgr.instructions;
  $: threadRecording = data.threadRecording;
  $: displayUserInfo = data.threadDisplayUserInfo;
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
    const supportVisionModels = (
      data.modelInfo.filter((model: api.AssistantModelLite) => model.supports_vision) || []
    ).map((model: api.AssistantModelLite) => model.id);
    supportsVision = supportVisionModels.includes(data.threadModel);
  }
  let visionSupportOverride: boolean | undefined;
  $: {
    visionSupportOverride =
      data.class?.ai_provider === 'azure'
        ? data.modelInfo.find((model: api.AssistantModelLite) => model.id === data.threadModel)
            ?.azure_supports_vision
        : undefined;
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
  let assistantVersion: number | null = null;
  let assistantInteractionMode: 'voice' | 'chat' | null = null;
  let allowUserFileUploads = true;
  let allowUserImageUploads = true;
  $: {
    const assistant = data.assistants.find(
      (assistant: api.Assistant) => assistant.id === $assistantId
    );
    if (assistant) {
      useLatex = assistant.use_latex || false;
      useImageDescriptions = assistant.use_image_descriptions || false;
      assistantInteractionMode = assistant.interaction_mode;
      assistantVersion = assistant.version ?? null;
      allowUserFileUploads = assistant.allow_user_file_uploads ?? true;
      allowUserImageUploads = assistant.allow_user_image_uploads ?? true;
    } else {
      useLatex = false;
      useImageDescriptions = false;
      assistantInteractionMode = null;
      assistantVersion = null;
      allowUserFileUploads = true;
      allowUserImageUploads = true;
      if (data.threadData.anonymous_session) {
        console.warn(`Definition for assistant ${$assistantId} not found.`);
      }
    }
  }
  $: statusComponents = (data.statusComponents || {}) as Partial<
    Record<string, api.StatusComponentUpdate[]>
  >;
  let latestIncidentUpdateTimestamps: Record<string, number> = {};
  $: latestIncidentUpdateTimestamps = computeLatestIncidentTimestamps(statusComponents);
  $: resolvedAssistantVersion = Number(assistantVersion ?? $version ?? 0);
  $: statusComponentId =
    $version >= 3 ? api.STATUS_COMPONENT_IDS.nextGen : api.STATUS_COMPONENT_IDS.classic;
  $: assistantStatusUpdates = filterLatestIncidentUpdates(
    statusComponents[statusComponentId],
    latestIncidentUpdateTimestamps
  );
  let showModerators = false;
  let showAssistantPrompt = false;
  let settingsOpen = false;

  function isFileCitation(a: api.TextAnnotation): a is api.TextAnnotationFileCitation {
    return a.type === 'file_citation' && a.text === 'responses_v3';
  }
  const getShortMessageTimestamp = (timestamp: number) => {
    return new Intl.DateTimeFormat('en-US', {
      hour: 'numeric',
      minute: 'numeric',
      hour12: true,
      timeZone: userTimezone
    }).format(new Date(timestamp * 1000));
  };

  const getMessageTimestamp = (timestamp: number) => {
    return new Intl.DateTimeFormat('en-US', {
      hour: 'numeric',
      minute: 'numeric',
      second: 'numeric',
      day: 'numeric',
      month: 'long',
      year: 'numeric',
      hour12: true,
      timeZoneName: 'short',
      timeZone: userTimezone
    }).format(new Date(timestamp * 1000));
  };

  let currentMessageAttachments: api.ServerFile[] = [];
  // Get the name of the participant in the chat thread.
  const getName = (message: api.OpenAIMessage) => {
    if (message.role === 'user') {
      if (message?.metadata?.is_current_user) {
        return data?.me?.user?.name || data?.me?.user?.email || 'Me';
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
      await threadMgr.fetchCodeInterpreterResult(content.run_id, content.step_id);
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

  const startNewChat = async () => {
    if (isAnonymousSession) {
      if (api.hasAnonymousShareToken()) {
        api.resetAnonymousSessionToken();
        await goto(
          `/group/${classId}/shared/assistant/${$assistantId}?share_token=${api.getAnonymousShareToken()}`
        );
      } else {
        sadToast('Cannot start a new chat in this anonymous session.');
      }
    } else {
      await goto(`/group/${classId}?assistant=${$assistantId}`);
    }
  };

  // Fallback link copy handling for environments (e.g., iframes) where Clipboard API is blocked
  let copyLinkModalOpen = false;
  let shareLink = '';
  let shareLinkInputEl: HTMLInputElement | null = null;

  type PermissionsPolicyLike = {
    allows?: (feature: string, origin?: string) => boolean;
    allowsFeature?: (feature: string) => boolean;
  };

  const canProgrammaticallyCopy = () => {
    try {
      // Check Permissions Policy if available to avoid triggering violations in iframes
      const d = document as unknown as {
        permissionsPolicy?: PermissionsPolicyLike;
        featurePolicy?: PermissionsPolicyLike;
      };
      const pol: PermissionsPolicyLike | undefined = d.permissionsPolicy ?? d.featurePolicy;
      if (pol) {
        if (typeof pol.allows === 'function' && !pol.allows('clipboard-write')) return false;
        if (typeof pol.allowsFeature === 'function' && !pol.allowsFeature('clipboard-write'))
          return false;
      }
      return !!navigator.clipboard && window.isSecureContext;
    } catch {
      return false;
    }
  };

  const openManualCopyModal = async (url: string) => {
    shareLink = url;
    copyLinkModalOpen = true;
    await tick();
    // Focus and select for quick manual copy (Cmd/Ctrl+C)
    shareLinkInputEl?.focus();
    shareLinkInputEl?.select();
  };

  const handleCopyLinkClick = async (e?: Event) => {
    e?.preventDefault?.();
    e?.stopPropagation?.();
    const url = `${$page.url.origin}/group/${classId}/thread/${threadId}`;
    if (canProgrammaticallyCopy()) {
      try {
        await navigator.clipboard.writeText(url);
        happyToast('Link copied to clipboard', 3000);
        return;
      } catch {
        // Fall through to manual copy
      }
    }
    // Manual copy fallback without using Clipboard API (avoids permissions policy violations)
    await openManualCopyModal(url);
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

  let confirmNavigation = true;
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
      confirmNavigation = false;
      if (isAnonymousSession) {
        if (api.hasAnonymousShareToken()) {
          api.resetAnonymousSessionToken();
          await goto(
            `/group/${classId}/shared/assistant/${$assistantId}?share_token=${api.getAnonymousShareToken()}`
          );
        } else {
          await goto(`/`, { invalidateAll: true });
        }
      } else {
        await goto(`/group/${classId}`, { invalidateAll: true });
      }
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
    wavStreamPlayer = new WavStreamPlayer({
      sampleRate: 24000,
      onAudioPartStarted: onAudioPartStartedProcessor
    });
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
    const audio = new Uint8Array(data.mono);
    const buffer = new ArrayBuffer(8 + audio.length);
    const view = new DataView(buffer);
    view.setFloat64(0, Date.now());
    new Uint8Array(buffer, 8).set(audio);
    socket.send(buffer);
  };

  /**
   * Handle the beginning of a new assistant message playback.
   * @param data The data associated with the new message.
   * @param data.trackId The ID of the track.
   * @param data.timestamp The timestamp of when the message started.
   */
  const onAudioPartStartedProcessor = (data: {
    trackId: string;
    eventId: string;
    timestamp: number;
  }) => {
    socket?.send(
      JSON.stringify({
        type: 'response.audio.delta.started',
        item_id: data.trackId,
        event_id: data.eventId,
        started_playing_at: data.timestamp
      })
    );
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
        case 'input_audio_buffer.speech_started': {
          if (!wavStreamPlayer) {
            sadToast('Failed to set up audio output to your speakers.');
            return;
          }
          await wavStreamPlayer.interrupt();
          const trackSampleOffset = await wavStreamPlayer.interrupt();
          if (trackSampleOffset?.trackId) {
            const { trackId, offset } = trackSampleOffset;
            if (!socket) {
              sadToast('Error connecting with the server.');
              return;
            }
            if (!wavRecorder) {
              sadToast('Failed to set up audio output to your speakers.');
              return;
            }
            socket.send(
              JSON.stringify({
                type: 'conversation.item.truncate',
                item_id: trackId,
                audio_end_ms: Math.floor((offset / wavStreamPlayer.getSampleRate()) * 1000)
              })
            );
          }
          break;
        }
        case 'response.audio.delta':
          if (!wavStreamPlayer) {
            sadToast('Failed to set up audio output to your speakers.');
            return;
          }
          wavStreamPlayer.add16BitPCM(
            base64ToArrayBuffer(message.audio),
            message.item_id,
            message.event_id
          );
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

  let showPlayer = false;
  let audioUrl: string | null = null;
  const fetchRecording = async () => {
    const res = await api.getThreadRecording(fetch, classId, threadId);
    const chunks: Uint8Array[] = [];

    for await (const chunk of await res) {
      if ((chunk as { type: string }).type === 'error') {
        sadToast(`Failed to load recording: ${(chunk as { detail: string }).detail}`);
        return;
      }
      chunks.push(chunk as Uint8Array);
    }

    const blob = new Blob(chunks, { type: 'audio/webm' });
    audioUrl = URL.createObjectURL(blob);
    showPlayer = true;
  };

  onNavigate(async () => {
    await resetAudioSession();
  });

  beforeNavigate((nav) => {
    if (
      (data.isSharedAssistantPage || data.isSharedThreadPage) &&
      isAnonymousSession &&
      confirmNavigation
    ) {
      if (
        !confirm(
          `${data.me.status === 'anonymous' ? 'You will lose access to this thread.' : "You won't be able to edit this thread."}\n\nAre you sure you want to leave this page?`
        )
      ) {
        nav.cancel();
        return;
      }
    }
  });
</script>

<div class="w-full flex flex-col justify-between grow min-h-0 relative">
  <div
    class={`overflow-y-auto pb-4 px-2 lg:px-4 ${
      data.isSharedAssistantPage || data.isSharedThreadPage ? 'pt-10' : ''
    }`}
    use:scroll={$messages}
  >
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
        : new Set([])}
      <div class="py-4 px-6 flex gap-x-3">
        <div class="shrink-0">
          {#if message.data.role === 'user'}
            <Avatar size="sm" src={getImage(message.data)} />
          {:else}
            <Logo size={8} />
          {/if}
        </div>
        <div class="max-w-full w-full">
          <div class="font-semibold text-blue-dark-40 mb-2 mt-1 flex flex-wrap items-center gap-2">
            <span class="flex items-center gap-2">
              {getName(message.data)}
              {#if message.data.role !== 'user' && !assistantDeleted}
                <AssistantVersionBadge version={$version} extraClasses="shrink-0" />
              {/if}
            </span>
            <span
              class="text-gray-500 text-xs font-normal ml-1 hover:underline"
              id={`short-timestamp-${message.data.id}`}
              >{getShortMessageTimestamp(message.data.created_at)}</span
            >
          </div>
          <Tooltip triggeredBy={`#short-timestamp-${message.data.id}`}>
            {getMessageTimestamp(message.data.created_at)}
          </Tooltip>
          {#each message.data.content as content}
            {#if content.type === 'text'}
              {@const { clean_string, images } = processString(content.text.value)}
              {@const imageInfo = convertImageProxyToInfo(images)}
              {@const quoteCitations = (content.text.annotations ?? []).filter(isFileCitation)}

              <div class="leading-6">
                <Markdown
                  content={parseTextContent(
                    { value: clean_string, annotations: content.text.annotations },
                    $version,
                    api.fullPath(`/class/${classId}/thread/${threadId}`)
                  )}
                  syntax={true}
                  latex={useLatex}
                />
              </div>
              {#if quoteCitations.length > 0}
                <div class="flex flex-wrap gap-2">
                  {#each quoteCitations as citation}
                    <FileCitation
                      name={citation.file_citation.file_name}
                      quote={citation.file_citation.quote}
                    />
                  {/each}
                </div>
              {/if}
              {#if attachment_file_ids.size > 0}
                <div class="flex flex-wrap gap-2">
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
                        <div>Code Interpreter Code</div>
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
                      <div>Output Image</div>
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
            {:else if content.type === 'code_output_image_url'}
              <Accordion flush>
                <AccordionItem>
                  <span slot="header"
                    ><div class="flex-row flex items-center space-x-2">
                      <div><ImageSolid size="lg" /></div>
                      <div>Output Image</div>
                    </div></span
                  >
                  <div class="leading-6 w-full">
                    <img
                      class="img-attachment m-auto"
                      src={content.url}
                      alt="Attachment generated by the assistant"
                    />
                  </div>
                </AccordionItem>
              </Accordion>
            {:else if content.type === 'code_output_logs'}
              <Accordion flush>
                <AccordionItem>
                  <span slot="header"
                    ><div class="flex-row flex items-center space-x-2">
                      <div><TerminalOutline size="lg" /></div>
                      <div>Output Logs</div>
                    </div></span
                  >
                  <div class="leading-6 w-full">
                    <pre style="white-space: pre-wrap;" class="text-black">{content.logs}</pre>
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
          {#if attachment_file_ids.size > 0}
            <div class="flex flex-wrap gap-2 mt-4">
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
            </div>
          {/if}
        </div>
      </div>
    {/each}
  </div>
  <Modal title="Group Moderators" bind:open={showModerators} autoclose outsideclose
    ><ModeratorsTable moderators={teachers} /></Modal
  >
  <Modal title="Assistant Prompt" size="lg" bind:open={showAssistantPrompt} autoclose outsideclose
    ><span class="whitespace-pre-wrap text-gray-700"
      ><Sanitize html={$threadInstructions ?? ''} /></span
    ></Modal
  >
  <Modal title="Copy Link" bind:open={copyLinkModalOpen} autoclose outsideclose>
    <div class="flex flex-col gap-3 p-1">
      <span class="text-sm text-gray-700">Press Cmd+C / Ctrl+C to copy the thread link.</span>
      <input
        class="w-full border border-gray-300 rounded-md px-2 py-1 text-sm text-gray-800 bg-gray-50"
        readonly
        bind:this={shareLinkInputEl}
        value={shareLink}
      />
      <div class="flex justify-end pt-1">
        <Button size="xs" color="alternative" on:click={() => (copyLinkModalOpen = false)}
          >Done</Button
        >
      </div>
    </div>
  </Modal>
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
          {#if !isPrivate && displayUserInfo}
            <div
              class="flex flex-col gap-1 border border-red-600 px-3 py-2 rounded-2xl max-w-sm items-center justify-center text-center my-5"
            >
              <UsersSolid class="h-10 w-10 text-red-600" />
              <span class="text-gray-700 text-sm font-normal"
                ><Button
                  class="p-0 text-gray-700 text-sm underline font-normal"
                  on:click={showModeratorsModal}
                  on:touchstart={showModeratorsModal}>Moderators</Button
                > have enabled a setting for this thread only that allows them to see the thread,
                <span class="font-semibold"
                  >your full name, and listen to a recording of your conversation</span
                >.</span
              >
            </div>
          {/if}
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
        <StatusErrors {assistantStatusUpdates} />
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
            visionAcceptedFiles={allowUserImageUploads ? visionAcceptedFiles : null}
            fileSearchAcceptedFiles={allowUserFileUploads ? fileSearchAcceptedFiles : null}
            codeInterpreterAcceptedFiles={allowUserFileUploads
              ? codeInterpreterAcceptedFiles
              : null}
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
            threadVersion={$version}
            assistantVersion={resolvedAssistantVersion}
            on:submit={handleSubmit}
            on:dismissError={handleDismissError}
            on:startNewChat={startNewChat}
          />
        {:else if data.threadInteractionMode === 'voice' && ($messages.length > 0 || assistantInteractionMode === 'chat')}
          {#if threadRecording && $messages.length > 0 && assistantInteractionMode === 'voice'}
            <div
              class="border relative flex gap-2 flex-wrap z-10 px-3.5 text-blue-dark-40 border-gray-500 bg-gray-100 -mb-3 rounded-t-2xl border-b-0 pb-5 pt-2.5"
            >
              <div class="w-full">
                {#if showPlayer && audioUrl}
                  <AudioPlayer bind:src={audioUrl} duration={threadRecording.duration} />
                {:else}
                  <div class="flex w-full flex-col items-center md:flex-row gap-2">
                    <div class="text-danger-000 flex flex-row items-center gap-2 md:w-full">
                      <div class="flex flex-col w-fit">
                        <div class="text-xs uppercase font-semibold">Recording available</div>
                        <div class="text-sm">
                          You can listen to a recording of this conversation.
                        </div>
                      </div>
                    </div>
                    <Button
                      class="text-white bg-gradient-to-b from-blue-dark-30 to-blue-dark-40 py-1 px-2 rounded-lg w-fit shrink-0 hover:from-blue-dark-40 hover:to-blue-dark-50 transition-all text-xs font-normal"
                      on:click={fetchRecording}
                    >
                      Load Recording
                    </Button>
                  </div>
                {/if}
              </div>
            </div>
          {/if}

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
            {#if !$published && isPrivate && !displayUserInfo}
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
              {#if displayUserInfo}
                {#if data.threadInteractionMode === 'voice'}
                  <div class="flex gap-2 items-start w-full text-sm flex-wrap lg:flex-nowrap">
                    <UsersSolid size="sm" class="text-orange pt-0" />
                    <Span class="text-gray-600 text-xs font-normal"
                      ><Button
                        class="p-0 text-gray-600 text-xs underline font-normal"
                        on:click={showModeratorsModal}
                        on:touchstart={showModeratorsModal}>Moderators</Button
                      > can see this thread,
                      <span class="font-semibold"
                        >{isCurrentUser ? 'your' : "the user's"} full name, and listen to a recording
                        of {isCurrentUser ? 'your' : 'the'} conversation</span
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
                      > can see this thread and
                      <span class="font-semibold"
                        >{isCurrentUser ? 'your' : "the user's"} full name</span
                      >. For more information, please review
                      <a href="/privacy-policy" rel="noopener noreferrer" class="underline"
                        >PingPong's privacy statement</a
                      >. Assistants can make mistakes. Check important info.</Span
                    >
                  </div>
                {/if}
              {:else}
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
              {/if}
            {:else}
              <EyeOutline size="sm" class="text-orange" />
              <Span class="text-gray-600 text-xs font-normal"
                >Everyone in this group can see this thread but not {isCurrentUser
                  ? 'your'
                  : "the user's"} name. {#if displayUserInfo}{#if data.threadInteractionMode === 'voice'}<Button
                      class="p-0 text-gray-600 text-xs underline font-normal"
                      on:click={showModeratorsModal}
                      on:touchstart={showModeratorsModal}>Moderators</Button
                    > can see this thread,
                    <span class="font-semibold"
                      >{isCurrentUser ? 'your' : "the user's"} full name, and listen to a recording of
                      {isCurrentUser ? 'your' : 'the'} conversation</span
                    >.{:else}<Button
                      class="p-0 text-gray-600 text-xs underline font-normal"
                      on:click={showModeratorsModal}
                      on:touchstart={showModeratorsModal}>Moderators</Button
                    > can see this thread and
                    <span class="font-semibold"
                      >{isCurrentUser ? 'your' : "the user's"} full name</span
                    >.{/if}{/if} Assistants can make mistakes. Check important info.</Span
              >
            {/if}
          </div>
          <button
            on:click|preventDefault={handleCopyLinkClick}
            title="Copy link"
            aria-label="Copy link"
            ><LinkOutline
              class="dark:text-white inline-block w-5 h-6 text-blue-dark-30 hover:text-blue-dark-50 active:animate-ping font-medium"
              size="lg"
            /></button
          >
          {#if !(data.threadInteractionMode === 'voice' && $messages.length === 0 && assistantInteractionMode === 'voice')}
            <div class="shrink-0 grow-0 h-auto">
              <CogOutline class="dark:text-white cursor-pointer w-6 h-4 font-light" size="lg" />
              <Dropdown bind:open={settingsOpen}>
                {#if $threadInstructions}
                  <DropdownItem
                    on:click={() => ((showAssistantPrompt = true), (settingsOpen = false))}
                  >
                    <span>Prompt</span>
                  </DropdownItem>
                  <DropdownDivider />
                {/if}
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
