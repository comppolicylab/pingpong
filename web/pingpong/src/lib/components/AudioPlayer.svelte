<script lang="ts">
  import { Button, Dropdown, DropdownItem, Popover } from 'flowbite-svelte';
  import { PauseSolid, PlaySolid } from 'flowbite-svelte-icons';
  import { onMount, onDestroy } from 'svelte';

  export let duration: number;
  export let src: string;

  let audioElement: HTMLAudioElement;
  let isPlaying = false;
  let currentTime = 0;
  let playbackRate = 1;
  let volume = 1;
  let nonMutedVolume = volume;
  $: isMuted = volume === 0;
  let isDragging = false;
  let seekTime = 0;
  let showVolumeSlider = false;
  let showSpeedDropdown = false;
  let isHoveringProgress = false;
  let hoverTime = 0;

  const playbackSpeeds = [0.5, 0.75, 1, 1.25, 1.5, 2];

  // Convert milliseconds to seconds for display
  $: durationInSeconds = duration / 1000;
  $: progress = durationInSeconds > 0 ? (currentTime / durationInSeconds) * 100 : 0;
  $: seekProgress = durationInSeconds > 0 ? (seekTime / durationInSeconds) * 100 : 0;
  $: hoverProgress = durationInSeconds > 0 ? (hoverTime / durationInSeconds) * 100 : 0;
  $: displayTime = isDragging ? seekTime : currentTime;

  const formatTime = (timeInSeconds: number): string => {
    const minutes = Math.floor(timeInSeconds / 60);
    const seconds = Math.floor(timeInSeconds % 60);
    return `${minutes.toString()}:${seconds.toString().padStart(2, '0')}`;
  };

  const togglePlay = () => {
    if (!audioElement) return;

    if (isPlaying) {
      audioElement.pause();
    } else {
      audioElement.play();
    }
  };

  const skipBackwards = () => {
    if (!audioElement) return;
    const newTime = Math.max(0, audioElement.currentTime - 15);
    audioElement.currentTime = newTime;
    currentTime = newTime;
  };

  const skipForward = () => {
    if (!audioElement) return;
    const newTime = Math.min(durationInSeconds, audioElement.currentTime + 15);
    audioElement.currentTime = newTime;
    currentTime = newTime;
  };

  let progressBar: HTMLElement;
  const handleProgressMouseDown = (event: MouseEvent) => {
    if (!audioElement) return;
    isDragging = true;
    updateSeekTime(event);
    window.addEventListener('mousemove', handleProgressMouseMove);
    window.addEventListener('mouseup', handleProgressMouseUp);
  };

  const handleProgressMouseMove = (event: MouseEvent) => {
    if (!isDragging) return;
    updateSeekTime(event);
  };

  const handleProgressHover = (event: MouseEvent) => {
    if (isDragging) return;
    if (!progressBar) return;

    const rect = progressBar.getBoundingClientRect();
    const hoverX = Math.max(0, Math.min(event.clientX - rect.left, rect.width));
    const percentage = hoverX / rect.width;
    hoverTime = percentage * durationInSeconds;
  };

  const handleProgressMouseUp = (event: MouseEvent) => {
    if (!isDragging) return;
    updateSeekTime(event);
    currentTime = seekTime;
    audioElement.currentTime = seekTime;
    isDragging = false;
    window.removeEventListener('mousemove', handleProgressMouseMove);
    window.removeEventListener('mouseup', handleProgressMouseUp);
  };

  const updateSeekTime = (event: MouseEvent) => {
    if (!progressBar) return;

    const rect = progressBar.getBoundingClientRect();
    const clickX = Math.max(0, Math.min(event.clientX - rect.left, rect.width));
    const percentage = clickX / rect.width;
    seekTime = percentage * durationInSeconds;
  };

  const toggleMute = () => {
    if (!audioElement) return;

    audioElement.muted = !audioElement.muted;
    if (audioElement.muted) {
      volume = 0;
    } else {
      volume = nonMutedVolume;
    }
  };

  const handleVolumeChange = (event: Event) => {
    const target = event.target as HTMLInputElement;
    const newVolume = parseFloat(target.value);
    volume = newVolume;
    if (audioElement) {
      audioElement.volume = newVolume;
      nonMutedVolume = newVolume;
    }
  };

  const selectPlaybackRate = (rate: number) => {
    playbackRate = rate;
    if (audioElement) {
      audioElement.playbackRate = rate;
    }
    showSpeedDropdown = false;
  };

  onMount(() => {
    if (audioElement) {
      audioElement.addEventListener('play', () => {
        isPlaying = true;
      });

      audioElement.addEventListener('pause', () => {
        isPlaying = false;
      });

      audioElement.addEventListener('timeupdate', () => {
        if (!isDragging) {
          currentTime = audioElement.currentTime;
        }
      });

      audioElement.addEventListener('ended', () => {
        isPlaying = false;
        currentTime = 0;
      });

      audioElement.volume = volume;
    }
  });

  onDestroy(() => {
    if (audioElement) {
      audioElement.pause();
    }
    window.removeEventListener('mousemove', handleProgressMouseMove);
    window.removeEventListener('mouseup', handleProgressMouseUp);
  });
</script>

<div class="mx-auto">
  <!-- Hidden audio element -->
  <audio bind:this={audioElement} {src} preload="metadata">
    <track kind="captions" />
  </audio>

  <div class="flex flex-row items-center space-x-4">
    <!-- Skip Backward Button -->
    <Button
      on:click={skipBackwards}
      class="text-gray-600 hover:text-gray-800 transition-colors p-0"
    >
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width="24"
        height="24"
        fill="currentColor"
        viewBox="0 0 16 16"
      >
        <path
          fill-rule="evenodd"
          d="M8 3a5 5 0 1 1-4.546 2.914.5.5 0 0 0-.908-.417A6 6 0 1 0 8 2z"
        />
        <path
          d="M8 4.466V.534a.25.25 0 0 0-.41-.192L5.23 2.308a.25.25 0 0 0 0 .384l2.36 1.966A.25.25 0 0 0 8 4.466"
        />
      </svg>
    </Button>

    <!-- Play/Pause Button -->
    <Button
      on:click={togglePlay}
      class="flex items-center justify-center bg-gray-800 text-white hover:bg-gray-700 transition-colors p-2 rounded-full"
    >
      {#if isPlaying}
        <PauseSolid class="w-6 h-6" />
      {:else}
        <PlaySolid class="w-6 h-6" />
      {/if}
    </Button>

    <!-- Skip Forward Button -->
    <Button on:click={skipForward} class="text-gray-600 hover:text-gray-800 transition-colors p-0">
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width="24"
        height="24"
        fill="currentColor"
        class="bi bi-arrow-clockwise"
        viewBox="0 0 16 16"
      >
        <path
          fill-rule="evenodd"
          d="M8 3a5 5 0 1 0 4.546 2.914.5.5 0 0 1 .908-.417A6 6 0 1 1 8 2z"
        />
        <path
          d="M8 4.466V.534a.25.25 0 0 1 .41-.192l2.36 1.966c.12.1.12.284 0 .384L8.41 4.658A.25.25 0 0 1 8 4.466"
        />
      </svg>
    </Button>

    <!-- Current Time -->
    <span class="text-sm font-medium text-gray-800 w-12">
      {formatTime(displayTime)}
    </span>

    <!-- Progress Bar Container -->
    <div class="flex-1 relative">
      <!-- Hover time tooltip -->
      {#if isHoveringProgress && !isDragging}
        <div
          class="absolute -top-8 bg-gray-800 text-white text-xs px-2 py-1 rounded transform -translate-x-1/2 z-10"
          style="left: {hoverProgress}%"
        >
          {formatTime(hoverTime)}
        </div>
      {:else if isHoveringProgress && isDragging}
        <div
          class="absolute -top-8 bg-gray-800 text-white text-xs px-2 py-1 rounded transform -translate-x-1/2 z-10"
          style="left: {seekProgress}%"
        >
          {formatTime(seekTime)}
        </div>
      {/if}

      <div
        class="progress-bar w-full h-2 bg-gray-200 rounded-full cursor-pointer relative"
        on:mousedown={handleProgressMouseDown}
        on:mouseenter={() => (isHoveringProgress = true)}
        on:mouseleave={() => (isHoveringProgress = false)}
        on:mousemove={handleProgressHover}
        bind:this={progressBar}
        role="slider"
        tabindex="0"
        aria-valuemin="0"
        aria-valuemax="100"
        aria-valuenow={isDragging ? seekProgress : progress}
      >
        <!-- Background track -->
        <div class="absolute inset-0 bg-gray-200 rounded-full"></div>

        <!-- Progress gradient -->
        <div
          class="h-full rounded-full relative overflow-hidden"
          style="width: {isDragging ? seekProgress : progress}%"
        >
          <div
            class="absolute inset-0 bg-gradient-to-r from-blue-500 from-80% to-blue-400 to-100%"
          ></div>
        </div>

        <!-- Always visible slider handle -->
        <div
          class="absolute top-1/2 transform -translate-y-1/2 -translate-x-1/2 w-4 h-4 bg-blue-500 rounded-full shadow-lg border-2 border-white cursor-grab active:cursor-grabbing"
          style="left: {isDragging ? seekProgress : progress}%"
        ></div>
      </div>
    </div>

    <!-- Total Duration -->
    <span class="text-sm font-medium text-gray-800 w-12">
      {formatTime(durationInSeconds)}
    </span>

    <!-- Volume Control -->
    <div
      class="relative volume-control-area"
      on:mouseenter={() => (showVolumeSlider = true)}
      on:mouseleave={() => (showVolumeSlider = false)}
      role="group"
    >
      <!-- Extended hover area -->
      <div
        class="absolute -top-16 -left-4 -right-4 bottom-0 {showVolumeSlider ? 'block' : 'hidden'}"
      ></div>

      <button
        on:click={toggleMute}
        id="volume-button"
        class="relative w-10 h-10 flex items-center justify-center text-gray-600 hover:text-gray-800"
      >
        <svg class="w-6 h-6" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <mask id="diagonal-mask" maskUnits="userSpaceOnUse">
            <rect width="24" height="24" fill="white" />
            <line
              x1="5"
              y1="3"
              x2="21"
              y2="19"
              stroke="black"
              stroke-width="1.5"
              class="transition-[stroke-dashoffset] duration-300 ease-in-out"
              style="stroke-dasharray: 23;"
              stroke-dashoffset={isMuted ? 0 : 23}
            />
          </mask>

          <g mask="url(#diagonal-mask)">
            <!-- Speaker -->
            <path d="M3 9v6h4l5 5V4L7 9H3z" />

            <!-- Small wave -->
            <path d="M16.5 12c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02z" />

            <!-- Large wave -->
            <path
              d="M14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"
              class={`origin-center transition-opacity translate-scale duration-300 ease-in-out`}
              class:opacity-100={volume === 0 || volume >= 0.5}
              class:scale-100={volume === 0 || volume >= 0.5}
              class:opacity-0={volume > 0 && volume < 0.5}
              class:scale-90={volume > 0 && volume < 0.5}
            />

            <!-- Slash line -->
            <line
              x1="4"
              y1="4"
              x2="20"
              y2="20"
              stroke="currentColor"
              stroke-width="2"
              class="transition-[stroke-dashoffset] duration-300 ease-in-out"
              style="stroke-dasharray: 23;"
              stroke-dashoffset={isMuted ? 0 : 23}
            />
          </g>
        </svg>
      </button>

      <Popover
        class="rounded-md shadow-md border z-20"
        arrow={false}
        bind:open={showVolumeSlider}
        triggeredBy="#volume-button"
      >
        <input
          type="range"
          min="0"
          max="1"
          step="0.01"
          value={volume}
          on:input={handleVolumeChange}
          class="bg-gray-200 rounded-lg appearance-none cursor-pointer volume-slider"
        />
      </Popover>
    </div>

    <!-- Speed Selector -->
    <div class="relative">
      <Button
        class="flex items-center justify-center w-12 h-8 text-sm font-medium text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded transition-colors"
      >
        {playbackRate}x
      </Button>

      <Dropdown
        class="bg-white rounded-lg shadow-lg border py-0 overflow-hidden"
        placement="top-end"
        bind:open={showSpeedDropdown}
      >
        {#each playbackSpeeds as speed}
          <DropdownItem
            on:click={() => selectPlaybackRate(speed)}
            class="block w-full px-3 py-1 text-sm font-light text-left hover:bg-gray-100 {speed ===
            playbackRate
              ? 'bg-blue-50 text-blue-600'
              : 'text-gray-700'}"
          >
            {speed}x
          </DropdownItem>
        {/each}
      </Dropdown>
    </div>
  </div>
</div>

<style>
  /* Volume slider styling */
  .volume-slider::-webkit-slider-thumb {
    appearance: none;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: #3b82f6;
    cursor: pointer;
    border: 2px solid white;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
  }

  .volume-slider::-moz-range-thumb {
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: #3b82f6;
    cursor: pointer;
    border: 2px solid white;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
  }

  .volume-slider::-webkit-slider-track {
    background: #e5e7eb;
    border-radius: 4px;
  }

  .volume-slider::-moz-range-track {
    background: #e5e7eb;
    border-radius: 4px;
  }
</style>
