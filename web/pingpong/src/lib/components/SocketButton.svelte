<script lang="ts">
  import { createAudioWebsocket } from '$lib/api';

    let socket: WebSocket;
    export let classId: number;
    export let threadId: number;
    
    import { onMount } from 'svelte';
  let mediaRecorder: MediaRecorder;
  let isRecording: boolean = false;

  // Establish the WebSocket connection and prepare the MediaRecorder when the component mounts.
  onMount(async () => {
    // Replace with your actual backend URL/port.
    socket = createAudioWebsocket(
      classId, threadId
    );
    socket.binaryType = "arraybuffer";

    socket.addEventListener("open", () => {
      console.log("WebSocket connection opened.");
      // Send an initial event message if needed:
      const initEvent = { type: "connection", message: "Client connected" };
      socket.send(JSON.stringify(initEvent));
    });

    socket.addEventListener("message", (event) => {
      console.log("Received message from server:", event.data);
    });

    socket.addEventListener("close", () => {
      console.log("WebSocket connection closed.");
    });

    // Request access to the user's microphone.
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaRecorder = new MediaRecorder(stream);

      // The ondataavailable event is triggered when a chunk of audio is ready.
      mediaRecorder.ondataavailable = async (event: BlobEvent) => {
        if (event.data.size > 0 && socket.readyState === WebSocket.OPEN) {
          // Convert the Blob to an ArrayBuffer before sending.
          const arrayBuffer = await event.data.arrayBuffer();
          socket.send(arrayBuffer);
        }
      };
    } catch (error) {
      console.error("Error accessing microphone:", error);
    }
  });

  // Function to start recording audio.
  function startRecording() {
    if (mediaRecorder && !isRecording) {
      isRecording = true;
      // Start recording; the argument is the timeslice in milliseconds (e.g., 100ms).
      mediaRecorder.start(100);
      // Optionally, send an event message to the server.
      const eventMessage = { type: "recording", status: "started" };
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify(eventMessage));
      }
    }
  }

  // Function to stop recording audio.
  function stopRecording() {
    if (mediaRecorder && isRecording) {
      isRecording = false;
      mediaRecorder.stop();
      // Send an event message to the server.
      const eventMessage = { type: "recording", status: "stopped" };
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify(eventMessage));
      }
    }
  }
</script>

<div>
    <button on:click={startRecording} disabled={isRecording}>
      Start Recording
    </button>
    <button on:click={stopRecording} disabled={!isRecording}>
      Stop Recording
    </button>
  </div>