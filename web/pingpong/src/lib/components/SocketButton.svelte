<script lang="ts">
  import { createAudioWebsocket } from '$lib/api';
  import { Button } from 'flowbite-svelte';
  import { MicrophoneOutline } from 'flowbite-svelte-icons';

  export let classId: number;
  export let threadId: number;

  let mediaRecorder: MediaRecorder;
  let isRecording: boolean = false;
  let socket: WebSocket;

  const decideAction = async () => {
    if (isRecording) {
      await stopRecording();
    } else {
      await startRecording();
    }
  };

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const devices = await navigator.mediaDevices.enumerateDevices();
      const microphones = devices.filter((device) => device.kind === 'audioinput');

      console.log(microphones);
      mediaRecorder = new MediaRecorder(stream);
      socket = createAudioWebsocket(classId, threadId);
      socket.binaryType = 'arraybuffer';

      socket.addEventListener('open', () => {
        console.log('WebSocket connection opened.');
        const initEvent = { type: 'connection', message: 'Client connected' };
        socket.send(JSON.stringify(initEvent));
      });

      socket.addEventListener('message', (event) => {
        console.log('Received message from server:', event.data);
      });

      socket.addEventListener('close', () => {
        console.log('WebSocket connection closed.');
      });

      socket.addEventListener('error', (error) => {
        console.error('WebSocket error:', error);
        socket.close();
      });

      mediaRecorder.ondataavailable = async (event: BlobEvent) => {
        if (event.data.size > 0 && socket.readyState === WebSocket.OPEN) {
          const arrayBuffer = await event.data.arrayBuffer();
          socket.send(arrayBuffer);
        }
      };
      isRecording = true;
      mediaRecorder.start(100);
      const eventMessage = { type: 'recording', status: 'started' };
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify(eventMessage));
      }
    } catch (error) {
      console.error('Error accessing microphone:', error);
    }
  };

  const stopRecording = async () => {
    if (mediaRecorder && isRecording) {
      isRecording = false;
      mediaRecorder.stop();
      const eventMessage = { type: 'recording', status: 'stopped' };
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify(eventMessage));
      }
      socket.close();
    }
  };
</script>

<Button
  type="button"
  color="blue"
  class="text-blue-700 hover:text-white p-1.5 w-8 h-8 bg-blue-light-40 border-transparent"
  on:click={decideAction}
>
  <slot name="icon">
    <MicrophoneOutline size="md" />
  </slot>
</Button>
