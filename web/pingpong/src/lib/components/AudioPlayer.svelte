<script lang="ts">
	import { Button, Dropdown, DropdownItem, Popover } from 'flowbite-svelte';
	import { PauseSolid, PlaySolid } from 'flowbite-svelte-icons';
	import { onMount, onDestroy } from 'svelte';

	interface Props {
		duration: number;
		src: string;
	}

	let { duration, src = $bindable() }: Props = $props();

	let audioElement: HTMLAudioElement | null = $state(null);
	let isPlaying = $state(false);
	let currentTime = $state(0);
	let playbackRate = $state(1);
	let volume = $state(1);
	let nonMutedVolume = $state(1);
	let isMuted = $derived(volume === 0);
	let isDragging = $state(false);
	let seekTime = $state(0);
	let showVolumeSlider = $state(false);
	let showSpeedDropdown = $state(false);
	let isHoveringProgress = $state(false);
	let hoverTime = $state(0);

	const playbackSpeeds = [0.5, 0.75, 1, 1.25, 1.5, 2];

	// Convert milliseconds to seconds for display
	let durationInSeconds = $derived(duration / 1000);
	let progress = $derived(durationInSeconds > 0 ? (currentTime / durationInSeconds) * 100 : 0);
	let seekProgress = $derived(durationInSeconds > 0 ? (seekTime / durationInSeconds) * 100 : 0);
	let hoverProgress = $derived(durationInSeconds > 0 ? (hoverTime / durationInSeconds) * 100 : 0);
	let displayTime = $derived(isDragging ? seekTime : currentTime);

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

	let progressBar: HTMLElement | null = $state(null);
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
		if (audioElement) {
			audioElement.currentTime = seekTime;
		}
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
				if (!isDragging && audioElement) {
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
		<Button onclick={skipBackwards} class="p-0 text-gray-600 transition-colors hover:text-gray-800">
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
			onclick={togglePlay}
			class="flex items-center justify-center rounded-full bg-gray-800 p-2 text-white transition-colors hover:bg-gray-700"
		>
			{#if isPlaying}
				<PauseSolid class="h-6 w-6" />
			{:else}
				<PlaySolid class="h-6 w-6" />
			{/if}
		</Button>

		<!-- Skip Forward Button -->
		<Button onclick={skipForward} class="p-0 text-gray-600 transition-colors hover:text-gray-800">
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
		<span class="w-12 text-sm font-medium text-gray-800">
			{formatTime(displayTime)}
		</span>

		<!-- Progress Bar Container -->
		<div class="relative flex-1">
			<!-- Hover time tooltip -->
			{#if isHoveringProgress && !isDragging}
				<div
					class="absolute -top-8 z-10 -translate-x-1/2 transform rounded-sm bg-gray-800 px-2 py-1 text-xs text-white"
					style="left: {hoverProgress}%"
				>
					{formatTime(hoverTime)}
				</div>
			{:else if isHoveringProgress && isDragging}
				<div
					class="absolute -top-8 z-10 -translate-x-1/2 transform rounded-sm bg-gray-800 px-2 py-1 text-xs text-white"
					style="left: {seekProgress}%"
				>
					{formatTime(seekTime)}
				</div>
			{/if}

			<div
				class="progress-bar relative h-2 w-full cursor-pointer rounded-full bg-gray-200"
				onmousedown={handleProgressMouseDown}
				onmouseenter={() => (isHoveringProgress = true)}
				onmouseleave={() => (isHoveringProgress = false)}
				onmousemove={handleProgressHover}
				bind:this={progressBar}
				role="slider"
				tabindex="0"
				aria-valuemin="0"
				aria-valuemax="100"
				aria-valuenow={isDragging ? seekProgress : progress}
			>
				<!-- Background track -->
				<div class="absolute inset-0 rounded-full bg-gray-200"></div>

				<!-- Progress gradient -->
				<div
					class="relative h-full overflow-hidden rounded-full"
					style="width: {isDragging ? seekProgress : progress}%"
				>
					<div
						class="absolute inset-0 bg-gradient-to-r from-blue-500 from-80% to-blue-400 to-100%"
					></div>
				</div>

				<!-- Always visible slider handle -->
				<div
					class="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 transform cursor-grab rounded-full border-2 border-white bg-blue-500 shadow-lg active:cursor-grabbing"
					style="left: {isDragging ? seekProgress : progress}%"
				></div>
			</div>
		</div>

		<!-- Total Duration -->
		<span class="w-12 text-sm font-medium text-gray-800">
			{formatTime(durationInSeconds)}
		</span>

		<!-- Volume Control -->
		<div
			class="volume-control-area relative"
			onmouseenter={() => (showVolumeSlider = true)}
			onmouseleave={() => (showVolumeSlider = false)}
			role="group"
		>
			<!-- Extended hover area -->
			<div
				class="absolute -top-16 -right-4 bottom-0 -left-4 {showVolumeSlider ? 'block' : 'hidden'}"
			></div>

			<button
				onclick={toggleMute}
				id="volume-button"
				class="relative flex h-10 w-10 items-center justify-center text-gray-600 hover:text-gray-800"
			>
				<svg class="h-6 w-6" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
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
							class="translate-scale origin-center transition-opacity duration-300 ease-in-out"
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
				class="z-20 rounded-md border shadow-md"
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
					oninput={handleVolumeChange}
					class="volume-slider cursor-pointer appearance-none rounded-lg bg-gray-200"
				/>
			</Popover>
		</div>

		<!-- Speed Selector -->
		<div class="relative">
			<Button
				class="flex h-8 w-12 items-center justify-center rounded-sm text-sm font-medium text-gray-600 transition-colors hover:bg-gray-100 hover:text-gray-800"
			>
				{playbackRate}x
			</Button>

			<Dropdown
				class="overflow-hidden rounded-lg border bg-white py-0 shadow-lg"
				placement="top-end"
				bind:open={showSpeedDropdown}
			>
				{#each playbackSpeeds as speed (speed)}
					<DropdownItem
						onclick={() => selectPlaybackRate(speed)}
						class="block w-full px-3 py-1 text-left text-sm font-light hover:bg-gray-100 {speed ===
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
