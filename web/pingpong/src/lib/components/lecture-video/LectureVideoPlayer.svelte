<script lang="ts">
	import {
		CheckOutline,
		CloseOutline,
		PauseSolid,
		PlaySolid,
		VolumeDownSolid,
		VolumeUpSolid,
		VolumeMuteSolid
	} from 'flowbite-svelte-icons';
	import { fade } from 'svelte/transition';

	function formatTime(ms: number): string {
		const totalSeconds = Math.floor(ms / 1000);
		const minutes = Math.floor(totalSeconds / 60);
		const seconds = totalSeconds % 60;
		return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
	}

	function clamp(value: number, min: number, max: number): number {
		return Math.min(Math.max(value, min), max);
	}

	type QuestionMarkerState = 'upcoming' | 'correct' | 'incorrect';
	type KeyboardActionIndicator = 'play' | 'pause' | 'mute' | 'unmute';

	const PREVIEW_WIDTH = 224;
	const PREVIEW_VIDEO_IDLE_DEACTIVATE_MS = 3000;
	const PREVIEW_VIDEO_SEEK_TOLERANCE_S = 0.15;
	const PREVIEW_FRAME_REDRAW_EPSILON_S = 0.001;
	const VOLUME_SLIDER_PADDING_PX = 5;
	const VOLUME_SLIDER_TRACK_WIDTH_PX = 54;
	const VOLUME_SLIDER_EXPANDED_WIDTH_PX = 76;
	const MARKER_CLUSTER_THRESHOLD_PX = 28;
	const MARKER_CLUSTER_COLLAPSE_DELAY_MS = 120;
	const OVERLAY_TEXT_SHADOW = 'text-shadow: rgb(0 0 0) 0 0 2px;';

	type QuestionMarker = {
		id: number;
		offsetMs: number;
		label: string;
		state: QuestionMarkerState;
	};

	type MarkerCluster = {
		key: string;
		markers: QuestionMarker[];
		centerPct: number;
	};

	function markerTickClass(state: QuestionMarkerState): string {
		switch (state) {
			case 'correct':
				return 'bg-emerald-400/90';
			case 'incorrect':
				return 'bg-rose-400/90';
			default:
				return 'bg-amber-300/90';
		}
	}

	function shouldFadeMarker(markerId: number, state: QuestionMarkerState): boolean {
		if (!condensedMarkerMode || state !== 'upcoming') return false;
		if (condensedMarkerIds.length < 2) return false;
		return markerId === condensedMarkerIds[condensedMarkerIds.length - 1];
	}

	function markerStateLabel(state: QuestionMarkerState): string {
		switch (state) {
			case 'correct':
				return 'answered correctly';
			case 'incorrect':
				return 'answered incorrectly';
			default:
				return 'upcoming';
		}
	}

	let {
		src,
		displayTitle = 'Lecture Video',
		startOffsetMs = 0,
		questionMarkers = [],
		subtitleText = null,
		disabled = false,
		manualPlaybackPrompt = false,
		activeQuestionIds = null,
		furthestOffsetMs = null,
		videoElement = $bindable(null),
		previewVideoElement = $bindable(null),
		currentTimeMs = $bindable(0),
		paused = $bindable(true),
		effectiveVolume = $bindable(1),
		ontimeupdate,
		onseek,
		onended,
		oncanplay,
		onplay,
		onpause,
		onerror,
		onquestionclick,
		onmanualplayrequest
	}: {
		src: string;
		displayTitle?: string;
		startOffsetMs?: number;
		questionMarkers?: QuestionMarker[];
		subtitleText?: string | null;
		disabled?: boolean;
		manualPlaybackPrompt?: boolean;
		activeQuestionIds?: number[] | null;
		furthestOffsetMs?: number | null;
		videoElement?: HTMLVideoElement | null;
		previewVideoElement?: HTMLVideoElement | null;
		currentTimeMs?: number;
		paused?: boolean;
		effectiveVolume?: number;
		ontimeupdate?: () => void;
		onseek?: (toOffsetMs: number, fromOffsetMs: number) => void;
		onended?: () => void;
		oncanplay?: () => void;
		onplay?: () => void;
		onpause?: () => void;
		onerror?: (e: Event) => void;
		onquestionclick?: (markerId: number) => void;
		onmanualplayrequest?: () => void;
	} = $props();

	let showControls = $state(false);
	let hideTimeout: ReturnType<typeof setTimeout> | null = $state(null);
	let durationMs = $state(0);
	let hoveringLockedSeek = $state(false);
	let pointerInsidePlayer = $state(false);
	let startedPlaybackOnce = $state(false);
	let condensedMarkerMode = $state(false);
	let condensedMarkerIds: number[] = $state([]);
	let showRemainingTime = $state(false);
	let volume = $state(1);
	let muted = $state(false);
	let volumeBeforeMute = $state(1);
	let showVolumeSlider = $state(false);
	let volumeHideTimeout: ReturnType<typeof setTimeout> | null = $state(null);
	let draggingVolume = $state(false);
	let draggingSeek = $state(false);
	let dragStartOffsetMs: number | null = $state(null);
	let dragPreviewOffsetMs: number | null = $state(null);
	let seekPreviewVisible = $state(false);
	let previewVideoActivated = $state(false);
	let seekPreviewOffsetMs = $state(0);
	let seekPreviewX = $state(0);
	let trackWidth = $state(0);
	let previewVideoReady = $state(false);
	let previewVideoFrameReady = $state(false);
	let lastCapturedPreviewFrameTimeS: number | null = $state(null);
	let snapshotCanvasHasFrame = $state(false);
	let lastPreviewVideoSrc: string | undefined = undefined;
	let lastMainVideoSrc: string | undefined = undefined;
	let keyboardActionIndicator: KeyboardActionIndicator | null = $state(null);
	let keyboardActionIndicatorTimeout: ReturnType<typeof setTimeout> | null = $state(null);
	let keyboardActionOverlayMounted = $state(false);
	let keyboardActionOverlayVisible = $state(false);
	let keyboardActionOverlayFresh = $state(false);
	let keyboardActionOverlayFreshTimeout: ReturnType<typeof setTimeout> | null = $state(null);
	let keyboardActionOverlayUnmountTimeout: ReturnType<typeof setTimeout> | null = $state(null);
	let mediaSessionRefreshTimeout: ReturnType<typeof setTimeout> | null = $state(null);
	let previewVideoDeactivateTimeout: ReturnType<typeof setTimeout> | null = $state(null);
	let snapshotCanvasElement: HTMLCanvasElement | null = $state(null);
	let playerContainerElement: HTMLDivElement | null = $state(null);
	let activeClusterKey: string | null = $state(null);
	let clusterCollapseTimeout: ReturnType<typeof setTimeout> | null = $state(null);

	let effectiveOffsetMs = $derived(
		draggingSeek ? (dragPreviewOffsetMs ?? currentTimeMs) : currentTimeMs
	);
	let progress = $derived(durationMs > 0 ? (effectiveOffsetMs / durationMs) * 100 : 0);
	let seekLimitOffsetMs = $derived(Math.max(currentTimeMs, furthestOffsetMs ?? 0));
	let seekLimitProgress = $derived(
		durationMs > 0 ? Math.min((seekLimitOffsetMs / durationMs) * 100, 100) : 0
	);
	let questionPendingControls = $derived(Boolean(activeQuestionIds?.length));
	let visibleControls = $derived(
		!manualPlaybackPrompt &&
			(questionPendingControls || (!disabled && (!startedPlaybackOnce || showControls)))
	);
	let visibleMarkers = $derived(
		condensedMarkerMode && condensedMarkerIds.length > 0
			? questionMarkers.filter((m) => condensedMarkerIds.includes(m.id))
			: questionMarkers
	);
	let markerNumberById: Map<number, number> = $derived.by(
		() => new Map(questionMarkers.map((marker, index) => [marker.id, index + 1]))
	);
	let markerClusters: MarkerCluster[] = $derived.by(() => {
		if (durationMs <= 0 || trackWidth <= 0 || visibleMarkers.length === 0) return [];
		const sorted = [...visibleMarkers].sort((a, b) => a.offsetMs - b.offsetMs);
		const clusters: MarkerCluster[] = [];
		for (const marker of sorted) {
			const pct = clamp((marker.offsetMs / durationMs) * 100, 0, 100);
			const px = (pct / 100) * trackWidth;
			const last = clusters[clusters.length - 1];
			if (last) {
				const lastMarker = last.markers[last.markers.length - 1];
				const lastMarkerPct = clamp((lastMarker.offsetMs / durationMs) * 100, 0, 100);
				const lastMarkerPx = (lastMarkerPct / 100) * trackWidth;
				if (Math.abs(px - lastMarkerPx) < MARKER_CLUSTER_THRESHOLD_PX) {
					last.markers.push(marker);
					const sumPct = last.markers.reduce(
						(s, m) => s + clamp((m.offsetMs / durationMs) * 100, 0, 100),
						0
					);
					last.centerPct = sumPct / last.markers.length;
					last.key = last.markers.map((m) => m.id).join('-');
					continue;
				}
			}
			clusters.push({ key: String(marker.id), markers: [marker], centerPct: pct });
		}
		return clusters;
	});
	let seekBarActive = $derived(seekPreviewVisible || draggingSeek);
	let knowledgeChecksVisible = $derived(!manualPlaybackPrompt && !seekBarActive);
	let previewVideoSrc = $derived(previewVideoActivated ? src : undefined);
	let previewVideoPreload: 'auto' | 'metadata' = $derived(
		previewVideoActivated ? 'auto' : 'metadata'
	);
	let previewDisplayOffsetMs = $derived(dragPreviewOffsetMs ?? seekPreviewOffsetMs);
	let previewTimeText = $derived(formatTime(previewDisplayOffsetMs));
	let hoverPercent = $derived(durationMs > 0 ? (previewDisplayOffsetMs / durationMs) * 100 : 0);
	let clampedPreviewX = $derived(
		clamp(seekPreviewX, PREVIEW_WIDTH / 2, trackWidth - PREVIEW_WIDTH / 2)
	);
	let displayedOffsetMs = $derived(
		startedPlaybackOnce ? effectiveOffsetMs : Math.max(effectiveOffsetMs, startOffsetMs)
	);
	let timeReadoutText = $derived(
		durationMs > 0
			? showRemainingTime
				? `-${formatTime(durationMs - displayedOffsetMs)} / ${formatTime(durationMs)}`
				: `${formatTime(displayedOffsetMs)} / ${formatTime(durationMs)}`
			: '--:-- / --:--'
	);
	let titleText = $derived(displayTitle.trim() || 'Lecture Video');

	function markerDisplayLabel(marker: QuestionMarker): string {
		const markerNumber = markerNumberById.get(marker.id);
		return markerNumber ? `${marker.label} ${markerNumber}` : marker.label;
	}

	function markerAriaLabel(marker: QuestionMarker): string {
		return `${markerDisplayLabel(marker)} - ${markerStateLabel(marker.state)}`;
	}

	function clearClusterCollapseTimeout() {
		if (clusterCollapseTimeout) {
			clearTimeout(clusterCollapseTimeout);
			clusterCollapseTimeout = null;
		}
	}

	function activateCluster(clusterKey: string) {
		clearClusterCollapseTimeout();
		activeClusterKey = clusterKey;
	}

	function scheduleClusterCollapse(clusterKey: string) {
		clearClusterCollapseTimeout();
		clusterCollapseTimeout = setTimeout(() => {
			if (activeClusterKey === clusterKey) activeClusterKey = null;
			clusterCollapseTimeout = null;
		}, MARKER_CLUSTER_COLLAPSE_DELAY_MS);
	}

	function toggleClusterExpansion(clusterKey: string) {
		clearClusterCollapseTimeout();
		activeClusterKey = activeClusterKey === clusterKey ? null : clusterKey;
	}

	function handleClusterFocusOut(event: FocusEvent, clusterKey: string) {
		const container = event.currentTarget;
		if (!(container instanceof HTMLDivElement)) return;
		if (event.relatedTarget instanceof Node && container.contains(event.relatedTarget)) return;
		scheduleClusterCollapse(clusterKey);
	}

	function syncMediaSessionPositionState() {
		if (typeof navigator === 'undefined' || !('mediaSession' in navigator) || !videoElement) {
			return;
		}
		if (!(durationMs > 0)) {
			return;
		}

		const durationSeconds = durationMs / 1000;
		const positionSeconds = Math.min(Math.max(currentTimeMs / 1000, 0), durationSeconds);

		try {
			navigator.mediaSession.setPositionState({
				duration: durationSeconds,
				playbackRate: videoElement.playbackRate || 1,
				position: positionSeconds
			});
		} catch {
			// Ignore browsers that partially expose MediaSession without position state support.
		}
	}

	function syncMediaSessionState() {
		if (typeof navigator === 'undefined' || !('mediaSession' in navigator)) {
			return;
		}

		try {
			navigator.mediaSession.playbackState = videoElement
				? paused
					? 'paused'
					: 'playing'
				: 'none';
		} catch {
			// Ignore unsupported playbackState assignments.
		}

		syncMediaSessionPositionState();
	}

	function forceMediaSessionUiRefresh() {
		if (typeof navigator === 'undefined' || !('mediaSession' in navigator)) return;

		const originalState = videoElement ? (paused ? 'paused' : 'playing') : 'none';
		if (originalState === 'none') return;

		const transientState = originalState === 'playing' ? 'paused' : 'playing';

		if (mediaSessionRefreshTimeout) {
			clearTimeout(mediaSessionRefreshTimeout);
			mediaSessionRefreshTimeout = null;
		}

		try {
			navigator.mediaSession.playbackState = transientState;
		} catch {
			return;
		}

		mediaSessionRefreshTimeout = setTimeout(() => {
			try {
				navigator.mediaSession.playbackState = originalState;
			} catch {
				// Ignore unsupported playbackState assignments.
			}
			syncMediaSessionPositionState();
			mediaSessionRefreshTimeout = null;
		}, 0);
	}

	$effect(() => {
		if (!seekPreviewVisible) return;
		syncPreviewVideo();
	});

	$effect(() => {
		if (src !== lastMainVideoSrc) {
			clearPreviewVideoDeactivateTimeout();
			previewVideoActivated = false;
			previewVideoReady = false;
			previewVideoFrameReady = false;
			lastCapturedPreviewFrameTimeS = null;
			clearSnapshotCanvas();
			lastPreviewVideoSrc = undefined;
			lastMainVideoSrc = src;
		}
	});

	$effect(() => {
		if (previewVideoSrc !== lastPreviewVideoSrc) {
			previewVideoReady = false;
			previewVideoFrameReady = false;
			lastCapturedPreviewFrameTimeS = null;
			lastPreviewVideoSrc = previewVideoSrc;
		}
	});

	$effect(() => {
		if (questionPendingControls) {
			showVolumeSlider = false;
			condensedMarkerMode = true;
			condensedMarkerIds = [...activeQuestionIds!];
			return;
		}
		if (!visibleControls) {
			condensedMarkerMode = false;
			condensedMarkerIds = [];
		}
	});

	$effect(() => {
		if (!knowledgeChecksVisible) {
			clearClusterCollapseTimeout();
			activeClusterKey = null;
		}
	});

	$effect(() => {
		if (activeClusterKey && !markerClusters.some((cluster) => cluster.key === activeClusterKey)) {
			activeClusterKey = null;
		}
	});

	$effect(() => () => clearClusterCollapseTimeout());

	$effect(() => {
		if (typeof navigator === 'undefined' || !('mediaSession' in navigator)) {
			return;
		}

		const mediaSession = navigator.mediaSession;
		const setActionHandler = (
			action:
				| 'play'
				| 'pause'
				| 'seekbackward'
				| 'seekforward'
				| 'seekto'
				| 'previoustrack'
				| 'nexttrack',
			handler: MediaSessionActionHandler | null
		) => {
			try {
				mediaSession.setActionHandler(action, handler);
			} catch {
				// Ignore unsupported media session actions.
			}
		};

		setActionHandler('play', () => {
			if (!videoElement || disabled || !videoElement.paused) return;
			void videoElement.play().catch(() => {});
		});
		setActionHandler('pause', () => {
			if (!videoElement || videoElement.paused) return;
			videoElement.pause();
		});
		setActionHandler('seekbackward', () => {
			syncMediaSessionPositionState();
			forceMediaSessionUiRefresh();
		});
		setActionHandler('seekforward', () => {
			syncMediaSessionPositionState();
			forceMediaSessionUiRefresh();
		});
		setActionHandler('seekto', () => {
			syncMediaSessionPositionState();
			forceMediaSessionUiRefresh();
		});
		setActionHandler('previoustrack', () => {});
		setActionHandler('nexttrack', () => {});

		return () => {
			setActionHandler('play', null);
			setActionHandler('pause', null);
			setActionHandler('seekbackward', null);
			setActionHandler('seekforward', null);
			setActionHandler('seekto', null);
			setActionHandler('previoustrack', null);
			setActionHandler('nexttrack', null);
		};
	});

	function handleTimeUpdate() {
		if (videoElement) {
			currentTimeMs = videoElement.currentTime * 1000;
			paused = videoElement.paused;
		}
		syncMediaSessionState();
		ontimeupdate?.();
	}

	function setMainVideoCurrentTime(offsetMs: number) {
		if (!videoElement) return;
		videoElement.currentTime = offsetMs / 1000;
		currentTimeMs = offsetMs;
		syncMediaSessionPositionState();
	}

	function handleLoadedMetadata() {
		setMainVideoCurrentTime(startOffsetMs);
	}

	function handleCanPlay() {
		if (videoElement) {
			durationMs = videoElement.duration * 1000;
			currentTimeMs = videoElement.currentTime * 1000;
		}
		syncMediaSessionState();
		oncanplay?.();
	}

	function handleEnded() {
		if (videoElement) {
			paused = videoElement.paused;
		}
		syncMediaSessionState();
		onended?.();
	}

	function handlePauseEvent() {
		if (videoElement) {
			paused = videoElement.paused;
		}
		showControls = true;
		scheduleHide();
		syncMediaSessionState();
		onpause?.();
	}

	function handlePlayEvent() {
		if (videoElement) {
			paused = videoElement.paused;
		}
		startedPlaybackOnce = true;
		showControls = true;
		scheduleHide();
		syncMediaSessionState();
		onplay?.();
	}

	function handleError(e: Event) {
		onerror?.(e);
	}

	function handleRateChange() {
		if (!videoElement) return;
		syncMediaSessionPositionState();
	}

	function handlePreviewVideoLoadedMetadata() {
		previewVideoReady = true;
		syncPreviewVideo();
	}

	function togglePlayPause() {
		if (disabled || questionPendingControls || !videoElement) return;
		if (videoElement.paused) {
			void videoElement.play().catch(() => {});
			return;
		}
		videoElement.pause();
	}

	function toggleMute() {
		if (!videoElement) return;
		if (muted || volume === 0) {
			muted = false;
			volume = volumeBeforeMute > 0 ? volumeBeforeMute : 1;
		} else {
			volumeBeforeMute = volume;
			muted = true;
		}
		videoElement.muted = muted;
		videoElement.volume = volume;
	}

	function setVolume(newVolume: number) {
		if (!videoElement) return;
		volume = clamp(newVolume, 0, 1);
		muted = volume === 0;
		videoElement.volume = volume;
		videoElement.muted = muted;
	}

	function handleVolumePointerDown(event: PointerEvent) {
		if (event.button !== 0) return;
		const slider = event.currentTarget;
		if (!(slider instanceof HTMLDivElement)) return;
		event.stopPropagation();
		event.preventDefault();
		slider.setPointerCapture(event.pointerId);
		draggingVolume = true;
		updateVolumeFromPointer(event, slider);
	}

	function handleVolumePointerMove(event: PointerEvent) {
		if (!draggingVolume) return;
		const slider = event.currentTarget;
		if (!(slider instanceof HTMLDivElement)) return;
		updateVolumeFromPointer(event, slider);
	}

	function handleVolumePointerUp(event: PointerEvent) {
		if (!draggingVolume) return;
		const slider = event.currentTarget;
		if (slider instanceof HTMLDivElement && slider.hasPointerCapture(event.pointerId)) {
			slider.releasePointerCapture(event.pointerId);
		}
		draggingVolume = false;
	}

	function updateVolumeFromPointer(event: PointerEvent, slider: HTMLDivElement) {
		const rect = slider.getBoundingClientRect();
		const ratio = clamp(
			(event.clientX - rect.left - VOLUME_SLIDER_PADDING_PX) /
				(rect.width - VOLUME_SLIDER_PADDING_PX * 2),
			0,
			1
		);
		setVolume(ratio);
	}

	function scheduleVolumeHide() {
		if (volumeHideTimeout) clearTimeout(volumeHideTimeout);
		volumeHideTimeout = setTimeout(() => {
			if (!draggingVolume) showVolumeSlider = false;
		}, 800);
	}

	$effect(() => {
		effectiveVolume = muted ? 0 : volume;
	});

	function handleContainerClick() {
		if (manualPlaybackPrompt) {
			startPlaybackFromUserGesture();
			return;
		}
		togglePlayPause();
	}

	function startPlaybackFromUserGesture() {
		if (onmanualplayrequest) {
			onmanualplayrequest();
			return;
		}
		if (disabled || !videoElement) return;
		void videoElement.play().catch(() => {});
	}

	function getSeekDetails(clientX: number, track: HTMLDivElement) {
		if (disabled || questionPendingControls || !videoElement || durationMs <= 0) return;

		const rect = track.getBoundingClientRect();
		const pointerOffsetPx = clamp(clientX - rect.left, 0, rect.width);
		const clickRatio = clamp(pointerOffsetPx / rect.width, 0, 1);
		const fromOffsetMs = dragStartOffsetMs ?? Math.round(videoElement.currentTime * 1000);
		const requestedOffsetMs = Math.round(durationMs * clickRatio);
		const allowedSeekOffsetMs = Math.max(fromOffsetMs, furthestOffsetMs ?? 0);
		const locked = requestedOffsetMs > allowedSeekOffsetMs;

		return {
			requestedOffsetMs,
			pointerOffsetPx,
			locked
		};
	}

	function syncPreviewVideo() {
		if (!previewVideoElement || !previewVideoReady) return;

		const nextPreviewTime = previewDisplayOffsetMs / 1000;
		if (
			Math.abs(previewVideoElement.currentTime - nextPreviewTime) < PREVIEW_VIDEO_SEEK_TOLERANCE_S
		) {
			markPreviewFrameReadyIfSynced();
			return;
		}

		previewVideoFrameReady = false;
		previewVideoElement.currentTime = nextPreviewTime;
	}

	function activatePreviewVideo() {
		if (!src) return;
		clearPreviewVideoDeactivateTimeout();
		if (previewVideoActivated) return;
		previewVideoActivated = true;
	}

	function clearPreviewVideoDeactivateTimeout() {
		if (!previewVideoDeactivateTimeout) return;
		clearTimeout(previewVideoDeactivateTimeout);
		previewVideoDeactivateTimeout = null;
	}

	function deactivatePreviewVideo() {
		clearPreviewVideoDeactivateTimeout();
		previewVideoActivated = false;
		previewVideoReady = false;
		previewVideoFrameReady = false;
		lastCapturedPreviewFrameTimeS = null;
		snapshotCanvasHasFrame = false;
	}

	function schedulePreviewVideoDeactivate(delayMs: number = PREVIEW_VIDEO_IDLE_DEACTIVATE_MS) {
		if (!previewVideoActivated) return;
		clearPreviewVideoDeactivateTimeout();
		previewVideoDeactivateTimeout = setTimeout(() => {
			if (seekPreviewVisible || draggingSeek) return;

			deactivatePreviewVideo();
		}, delayMs);
	}

	function markPreviewFrameReadyIfSynced() {
		if (!previewVideoElement || !previewVideoReady) return;
		if (previewVideoElement.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return;

		const nextPreviewTime = previewDisplayOffsetMs / 1000;
		if (
			Math.abs(previewVideoElement.currentTime - nextPreviewTime) >= PREVIEW_VIDEO_SEEK_TOLERANCE_S
		) {
			return;
		}

		previewVideoFrameReady = true;
		if (
			lastCapturedPreviewFrameTimeS != null &&
			Math.abs(lastCapturedPreviewFrameTimeS - previewVideoElement.currentTime) <
				PREVIEW_FRAME_REDRAW_EPSILON_S
		) {
			return;
		}

		captureSnapshotFromVideo(previewVideoElement);
		lastCapturedPreviewFrameTimeS = previewVideoElement.currentTime;
	}

	function clearSnapshotCanvas() {
		if (!snapshotCanvasElement) return;
		const ctx = snapshotCanvasElement.getContext('2d');
		if (!ctx) return;
		ctx.clearRect(0, 0, snapshotCanvasElement.width, snapshotCanvasElement.height);
		snapshotCanvasHasFrame = false;
	}

	function captureSnapshotFromVideo(sourceVideo: HTMLVideoElement | null) {
		if (!snapshotCanvasElement || !sourceVideo) return;
		if (sourceVideo.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return;
		const ctx = snapshotCanvasElement.getContext('2d');
		if (!ctx) return;
		const sourceWidth = sourceVideo.videoWidth;
		const sourceHeight = sourceVideo.videoHeight;
		if (sourceWidth === 0 || sourceHeight === 0) return;

		if (
			snapshotCanvasElement.width !== sourceWidth ||
			snapshotCanvasElement.height !== sourceHeight
		) {
			snapshotCanvasElement.width = sourceWidth;
			snapshotCanvasElement.height = sourceHeight;
		} else {
			ctx.clearRect(0, 0, sourceWidth, sourceHeight);
		}

		ctx.drawImage(sourceVideo, 0, 0, sourceWidth, sourceHeight);
		snapshotCanvasHasFrame = true;
	}

	function captureMainVideoSnapshot() {
		captureSnapshotFromVideo(videoElement);
	}

	function showSeekPreview(pointerOffsetPx: number, offsetMs: number) {
		activatePreviewVideo();
		if (!seekPreviewVisible && !snapshotCanvasHasFrame) {
			captureMainVideoSnapshot();
		}
		seekPreviewVisible = true;
		seekPreviewX = pointerOffsetPx;
		seekPreviewOffsetMs = offsetMs;
		syncPreviewVideo();
	}

	function hideSeekPreview() {
		seekPreviewVisible = false;
		schedulePreviewVideoDeactivate();
	}

	function updateSeekPreviewFromClientX(clientX: number, track: HTMLDivElement) {
		const details = getSeekDetails(clientX, track);
		if (!details) {
			hoveringLockedSeek = false;
			hideSeekPreview();
			return;
		}

		hoveringLockedSeek = details.locked;
		if (details.locked) {
			hideSeekPreview();
			return;
		}

		showSeekPreview(details.pointerOffsetPx, details.requestedOffsetMs);
		if (draggingSeek) {
			previewSeek(details.requestedOffsetMs);
		}
	}

	function handleSeekHover(event: MouseEvent) {
		const track = event.currentTarget;
		if (!(track instanceof HTMLDivElement)) {
			hoveringLockedSeek = false;
			return;
		}

		updateSeekPreviewFromClientX(event.clientX, track);
	}

	function handleSeekMouseEnter(event: MouseEvent) {
		handleSeekHover(event);
	}

	function previewSeek(offsetMs: number) {
		if (disabled || questionPendingControls) return;
		dragPreviewOffsetMs = offsetMs;
	}

	function cancelSeekInteraction(
		track: HTMLDivElement | null,
		pointerId: number | null,
		{ syncToPlayback = false }: { syncToPlayback?: boolean } = {}
	) {
		if (track && pointerId != null && track.hasPointerCapture(pointerId)) {
			track.releasePointerCapture(pointerId);
		}

		draggingSeek = false;
		dragStartOffsetMs = null;
		dragPreviewOffsetMs = null;
		hoveringLockedSeek = false;
		hideSeekPreview();

		if (syncToPlayback && videoElement) {
			currentTimeMs = Math.round(videoElement.currentTime * 1000);
		}
	}

	function commitSeek(offsetMs: number, fromOffsetMs: number) {
		if (disabled || questionPendingControls || !videoElement) return;
		setMainVideoCurrentTime(offsetMs);
		onseek?.(offsetMs, fromOffsetMs);
	}

	function handleSeekPointerDown(event: PointerEvent) {
		if (event.button !== 0 || disabled || questionPendingControls) return;

		const track = event.currentTarget;
		if (!(track instanceof HTMLDivElement) || !videoElement) return;

		event.stopPropagation();
		event.preventDefault();
		const details = getSeekDetails(event.clientX, track);
		if (!details) return;
		if (details.locked) {
			hoveringLockedSeek = true;
			hideSeekPreview();
			return;
		}

		track.setPointerCapture(event.pointerId);
		draggingSeek = true;
		dragStartOffsetMs = Math.round(videoElement.currentTime * 1000);
		hoveringLockedSeek = details.locked;
		showSeekPreview(details.pointerOffsetPx, details.requestedOffsetMs);
		previewSeek(details.requestedOffsetMs);
	}

	function handleSeekPointerMove(event: PointerEvent) {
		const track = event.currentTarget;
		if (!(track instanceof HTMLDivElement)) return;
		if (disabled || questionPendingControls) {
			if (draggingSeek) {
				cancelSeekInteraction(track, event.pointerId, { syncToPlayback: true });
			}
			return;
		}

		if (!draggingSeek) {
			if (event.buttons !== 0) return;
			updateSeekPreviewFromClientX(event.clientX, track);
			return;
		}

		const details = getSeekDetails(event.clientX, track);
		if (!details) return;

		hoveringLockedSeek = details.locked;
		if (details.locked) {
			cancelSeekInteraction(track, event.pointerId, { syncToPlayback: true });
			return;
		}

		updateSeekPreviewFromClientX(event.clientX, track);
	}

	function finishSeekDrag(event: PointerEvent) {
		const track = event.currentTarget;
		if (!(track instanceof HTMLDivElement)) return;
		if (disabled || questionPendingControls) {
			cancelSeekInteraction(track, event.pointerId, { syncToPlayback: true });
			return;
		}
		if (!draggingSeek) return;

		const details = getSeekDetails(event.clientX, track);
		const fromOffsetMs = dragStartOffsetMs ?? Math.round(videoElement?.currentTime ?? 0) * 1000;
		if (details == null || details.locked) {
			cancelSeekInteraction(track, event.pointerId, { syncToPlayback: true });
			return;
		}

		cancelSeekInteraction(track, event.pointerId);

		if (details.requestedOffsetMs !== fromOffsetMs) {
			commitSeek(details.requestedOffsetMs, fromOffsetMs);
		}
	}

	function cancelSeekDrag(event: PointerEvent) {
		const track = event.currentTarget;
		if (!(track instanceof HTMLDivElement)) return;
		if (disabled || questionPendingControls) {
			cancelSeekInteraction(track, event.pointerId, { syncToPlayback: true });
			return;
		}
		if (!draggingSeek) return;
		cancelSeekInteraction(track, event.pointerId, { syncToPlayback: true });
	}

	function scheduleHide(delayMs: number = 3000) {
		if (hideTimeout) {
			clearTimeout(hideTimeout);
		}
		hideTimeout = setTimeout(() => {
			if (
				pointerInsidePlayer ||
				draggingSeek ||
				draggingVolume ||
				seekPreviewVisible ||
				showVolumeSlider
			) {
				scheduleHide(delayMs);
				return;
			}
			showControls = false;
		}, delayMs);
	}

	function handleMouseMove() {
		if (disabled) return;
		showControls = true;
		scheduleHide();
	}

	function handleMouseEnter() {
		if (disabled) return;
		pointerInsidePlayer = true;
		showControls = true;
		scheduleHide();
	}

	function handleMouseLeave() {
		pointerInsidePlayer = false;
		if (hideTimeout) {
			clearTimeout(hideTimeout);
		}
		hoveringLockedSeek = false;
		hideSeekPreview();
		showControls = false;
	}

	function showKeyboardIndicator(action: KeyboardActionIndicator) {
		if (keyboardActionIndicatorTimeout) {
			clearTimeout(keyboardActionIndicatorTimeout);
		}
		if (keyboardActionOverlayUnmountTimeout) {
			clearTimeout(keyboardActionOverlayUnmountTimeout);
			keyboardActionOverlayUnmountTimeout = null;
		}
		if (keyboardActionOverlayFreshTimeout) {
			clearTimeout(keyboardActionOverlayFreshTimeout);
			keyboardActionOverlayFreshTimeout = null;
		}

		const shouldAnimateIn = !keyboardActionOverlayMounted;
		keyboardActionIndicator = action;
		keyboardActionOverlayMounted = true;
		keyboardActionOverlayVisible = true;
		keyboardActionOverlayFresh = shouldAnimateIn;

		if (shouldAnimateIn) {
			keyboardActionOverlayFreshTimeout = setTimeout(() => {
				keyboardActionOverlayFresh = false;
				keyboardActionOverlayFreshTimeout = null;
			}, 180);
		}

		keyboardActionIndicatorTimeout = setTimeout(() => {
			keyboardActionIndicatorTimeout = null;
			keyboardActionOverlayVisible = false;
			keyboardActionOverlayFresh = false;
			keyboardActionOverlayUnmountTimeout = setTimeout(() => {
				if (!keyboardActionOverlayVisible) {
					keyboardActionOverlayMounted = false;
					keyboardActionIndicator = null;
				}
				keyboardActionOverlayUnmountTimeout = null;
			}, 220);
		}, 450);
	}

	function handleKeyboardPlayPause() {
		if (manualPlaybackPrompt) {
			showKeyboardIndicator('play');
			startPlaybackFromUserGesture();
			return;
		}
		if (disabled || !videoElement) return;
		showKeyboardIndicator(videoElement.paused ? 'play' : 'pause');
		togglePlayPause();
	}

	function handleKeyboardMuteToggle() {
		if (!videoElement) return;
		showKeyboardIndicator(muted || volume === 0 ? 'unmute' : 'mute');
		toggleMute();
	}

	function isKeyboardEventWithinPlayer(event: KeyboardEvent): boolean {
		if (!playerContainerElement) return false;

		const eventTarget = event.target;
		const targetInsidePlayer =
			eventTarget instanceof Node && playerContainerElement.contains(eventTarget);
		const activeElementInsidePlayer =
			typeof document !== 'undefined' &&
			document.activeElement instanceof Node &&
			playerContainerElement.contains(document.activeElement);

		return targetInsidePlayer || activeElementInsidePlayer;
	}

	function handleKeydown(event: KeyboardEvent) {
		if (!isKeyboardEventWithinPlayer(event)) return;

		if (event.key === ' ' || event.key === 'k' || event.key === 'K') {
			event.preventDefault();
			handleKeyboardPlayPause();
		} else if (event.key === 'm' || event.key === 'M') {
			event.preventDefault();
			handleKeyboardMuteToggle();
		}
	}
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
	bind:this={playerContainerElement}
	class="relative overflow-hidden rounded-3xl border border-slate-800/80 bg-black"
	onkeydown={handleKeydown}
	onmousemove={handleMouseMove}
	onmouseenter={handleMouseEnter}
	onmouseleave={handleMouseLeave}
>
	{#if keyboardActionOverlayMounted && keyboardActionIndicator != null}
		<div
			class="pointer-events-none absolute inset-0 z-20 flex items-center justify-center transition-opacity duration-200 {keyboardActionOverlayVisible
				? 'opacity-100'
				: 'opacity-0'}"
		>
			<div
				class="flex h-24 w-24 items-center justify-center rounded-full bg-black/45 backdrop-blur-sm transition-transform duration-200 {keyboardActionOverlayVisible
					? 'scale-100'
					: 'scale-95'} {keyboardActionOverlayFresh ? 'scale-75' : ''}"
			>
				{#if keyboardActionIndicator === 'play'}
					<PlaySolid class="size-16 translate-x-0.5 text-white" />
				{:else if keyboardActionIndicator === 'pause'}
					<PauseSolid class="size-14 text-white" />
				{:else if keyboardActionIndicator === 'mute'}
					<VolumeMuteSolid class="size-12 text-white" />
				{:else}
					<VolumeUpSolid class="size-12 text-white" />
				{/if}
			</div>
		</div>
	{/if}

	<!-- svelte-ignore a11y_media_has_caption -->
	<video
		bind:this={videoElement}
		{src}
		playsinline
		preload="auto"
		tabindex={0}
		class="h-full w-full object-contain {disabled ? 'pointer-events-none' : ''}"
		onclick={handleContainerClick}
		ontimeupdate={handleTimeUpdate}
		oncanplay={handleCanPlay}
		onended={handleEnded}
		onplay={handlePlayEvent}
		onpause={handlePauseEvent}
		onratechange={handleRateChange}
		onerror={handleError}
		onloadedmetadata={handleLoadedMetadata}
	></video>

	{#if manualPlaybackPrompt}
		<div class="absolute inset-0 z-10 flex items-center justify-center px-6">
			<button
				class="flex h-24 w-24 items-center justify-center rounded-full border border-white/20 bg-black/60 text-white shadow-2xl backdrop-blur-md transition duration-150 hover:scale-105 hover:bg-black/70"
				onclick={(event: MouseEvent) => {
					event.stopPropagation();
					startPlaybackFromUserGesture();
				}}
				aria-label="Play lecture video"
			>
				<PlaySolid class="size-11 translate-x-0.5 text-white" />
			</button>
		</div>
	{/if}

	{#if visibleControls && subtitleText == null}
		<div
			class="pointer-events-none absolute inset-x-0 top-4 z-[11] hidden justify-center px-4 sm:flex"
		>
			<div class="pointer-events-auto rounded-full bg-black/30 p-1">
				<div
					class="flex h-8 items-center rounded-full px-3 text-sm font-medium text-white"
					style={OVERLAY_TEXT_SHADOW}
				>
					<span class="max-w-[32rem] truncate">{titleText}</span>
				</div>
			</div>
		</div>
	{/if}

	{#if subtitleText != null}
		<div class="pointer-events-none absolute inset-x-0 top-4 z-[11] flex justify-center px-4">
			<span class="rounded bg-black/70 px-3 py-1 text-center text-sm text-white">
				{subtitleText}
			</span>
		</div>
	{/if}

	{#if (!disabled || questionPendingControls) && !manualPlaybackPrompt}
		<div
			class="pointer-events-none absolute inset-x-0 bottom-0 transition-opacity duration-200 ease-out select-none"
			style="opacity: {visibleControls ? 1 : 0};"
		>
			<div class="px-4 pt-10">
				<div
					class="pointer-events-none relative mb-1 transition-all duration-200 ease-out"
					style="opacity: {knowledgeChecksVisible
						? 1
						: 0}; transform: translateY({knowledgeChecksVisible ? 0 : 6}px);"
				>
					{#snippet diamond(state: QuestionMarkerState)}
						<div
							class="relative flex size-3.5 shrink-0 items-center justify-center [filter:drop-shadow(0_1px_1px_rgba(0,0,0,0.3))]"
						>
							{#if state === 'correct'}
								<div
									class="absolute inset-0 rotate-45 rounded-sm border border-emerald-700 bg-emerald-500"
								></div>
								<CheckOutline class="relative z-10 size-2 text-white" />
							{:else if state === 'incorrect'}
								<div
									class="absolute inset-0 rotate-45 rounded-sm border border-rose-700 bg-rose-500"
								></div>
								<CloseOutline class="relative z-10 size-2 text-white" />
							{:else}
								<div
									class="absolute inset-0 rotate-45 rounded-sm border border-amber-600 bg-amber-400"
								></div>
								<span class="relative z-10 text-[8px] leading-none font-bold text-white">?</span>
							{/if}
						</div>
					{/snippet}
					{#if durationMs > 0}
						{#each markerClusters as cluster (cluster.key)}
							{@const isActive = activeClusterKey === cluster.key}
							{@const isMulti = cluster.markers.length > 1}
							{@const clusterInteractive =
								knowledgeChecksVisible &&
								cluster.markers.some((marker) => marker.state !== 'upcoming')}
							{@const fadeDuration = cluster.markers.some((m) => shouldFadeMarker(m.id, m.state))
								? 300
								: 0}
							<div
								class="absolute bottom-0 -translate-x-1/2 {clusterInteractive
									? 'pointer-events-auto'
									: 'pointer-events-none'}"
								style="left: {cluster.centerPct}%;"
								in:fade={{ duration: fadeDuration }}
								onmouseenter={() => {
									if (clusterInteractive) activateCluster(cluster.key);
								}}
								onmouseleave={() => {
									if (activeClusterKey === cluster.key) scheduleClusterCollapse(cluster.key);
								}}
								onfocusin={() => {
									if (clusterInteractive) activateCluster(cluster.key);
								}}
								onfocusout={(event) => handleClusterFocusOut(event, cluster.key)}
							>
								<div class="rounded-xl bg-black/30 p-1">
									{#if isMulti}
										{#key `${cluster.key}-${isActive ? 'expanded' : 'compact'}`}
											{#if !isActive}
												<button
													type="button"
													class="flex items-center rounded-lg px-1.5 py-1 transition-colors duration-150 ease-out disabled:cursor-default {clusterInteractive
														? 'cursor-pointer hover:bg-white/10 focus-visible:bg-white/10'
														: ''}"
													aria-label={`Show ${cluster.markers.length} comprehension checks`}
													aria-expanded={clusterInteractive ? isActive : undefined}
													disabled={!clusterInteractive}
													onclick={(e) => {
														e.stopPropagation();
														if (clusterInteractive) toggleClusterExpansion(cluster.key);
													}}
												>
													{#each cluster.markers as marker, idx (marker.id)}
														<div class="relative {idx > 0 ? '-ml-1.5' : ''}">
															{@render diamond(marker.state)}
														</div>
													{/each}
													<span
														class="ml-1.5 text-[10px] leading-none font-semibold text-white tabular-nums"
														style={OVERLAY_TEXT_SHADOW}
													>
														×{cluster.markers.length}
													</span>
												</button>
											{:else}
												<div
													class="flex flex-col gap-0.5 rounded-lg pb-0.5"
													transition:fade={{ duration: 100 }}
												>
													{#each cluster.markers as marker (marker.id)}
														{@const itemInteractive =
															knowledgeChecksVisible && marker.state !== 'upcoming'}
														<button
															type="button"
															class="flex items-center gap-1.5 rounded px-1.5 py-1 text-left transition-colors duration-150 ease-out disabled:cursor-default {itemInteractive
																? 'cursor-pointer hover:bg-white/10 focus-visible:bg-white/10'
																: ''}"
															aria-label={markerAriaLabel(marker)}
															disabled={!itemInteractive}
															onclick={(e) => {
																e.stopPropagation();
																activeClusterKey = null;
																onquestionclick?.(marker.id);
															}}
														>
															{@render diamond(marker.state)}
															<span
																class="text-[10px] leading-tight font-medium whitespace-nowrap text-white"
																style={OVERLAY_TEXT_SHADOW}
															>
																{markerDisplayLabel(marker)}
															</span>
														</button>
													{/each}
												</div>
											{/if}
										{/key}
									{:else}
										{@const marker = cluster.markers[0]}
										{@const markerInteractive =
											knowledgeChecksVisible && marker.state !== 'upcoming'}
										<div class="relative">
											<div
												class="pointer-events-none absolute bottom-full left-1/2 mb-2 transition-all duration-150 ease-out"
												style="transform: translateX(-50%) translateY({isActive
													? '0px'
													: '4px'}); opacity: {isActive ? 1 : 0};"
											>
												<div
													class="rounded-md bg-slate-900/95 px-2 py-1 text-[10px] font-medium tracking-wide whitespace-nowrap text-white shadow-lg ring-1 ring-white/10"
												>
													{markerDisplayLabel(marker)}
												</div>
											</div>
											<button
												type="button"
												class="flex items-center justify-center rounded-lg px-1.5 py-1 transition-colors duration-200 ease-out disabled:cursor-default {markerInteractive
													? 'cursor-pointer hover:bg-white/10 focus-visible:bg-white/10'
													: ''}"
												aria-label={markerAriaLabel(marker)}
												disabled={!markerInteractive}
												onclick={(e) => {
													e.stopPropagation();
													activeClusterKey = null;
													onquestionclick?.(marker.id);
												}}
											>
												{@render diamond(marker.state)}
											</button>
										</div>
									{/if}
								</div>
							</div>
						{/each}
					{/if}
				</div>
				<!-- svelte-ignore a11y_click_events_have_key_events -->
				<!-- svelte-ignore a11y_no_static_element_interactions -->
				<div class="pointer-events-auto cursor-default pb-4" onclick={(e) => e.stopPropagation()}>
					<div
						bind:clientWidth={trackWidth}
						class="pointer-events-auto relative py-2 {hoveringLockedSeek
							? 'cursor-not-allowed'
							: 'cursor-pointer'}"
						onclick={(event: MouseEvent) => {
							event.stopPropagation();
						}}
						onpointerdown={handleSeekPointerDown}
						onpointermove={handleSeekPointerMove}
						onpointerup={finishSeekDrag}
						onpointercancel={cancelSeekDrag}
						onmouseenter={handleSeekMouseEnter}
						onmousemove={handleSeekHover}
						onmouseleave={() => {
							hoveringLockedSeek = false;
							hideSeekPreview();
						}}
					>
						<div
							class="pointer-events-none absolute bottom-full z-10 mb-2 flex w-56 max-w-72 flex-col items-center gap-1.5 transition-opacity duration-200 ease-out"
							style="left: {clampedPreviewX}px; transform: translateX(-50%); opacity: {seekPreviewVisible
								? 1
								: 0};"
						>
							<div
								class="w-full overflow-hidden rounded-lg border border-slate-200/90 bg-slate-950 bg-clip-border shadow-xl"
							>
								<div class="relative aspect-video overflow-hidden bg-slate-900">
									<canvas
										bind:this={snapshotCanvasElement}
										class="absolute inset-0 h-full w-full object-cover"
									></canvas>
									<video
										bind:this={previewVideoElement}
										src={previewVideoSrc}
										playsinline
										muted
										preload={previewVideoPreload}
										class="absolute inset-0 h-full w-full object-cover"
										style="opacity: {previewVideoFrameReady ? 1 : 0};"
										onloadedmetadata={handlePreviewVideoLoadedMetadata}
										onloadeddata={markPreviewFrameReadyIfSynced}
										onseeked={markPreviewFrameReadyIfSynced}
									></video>
								</div>
							</div>
							{#key previewTimeText}
								<div class="rounded-full bg-black/30 p-1 shadow-lg">
									<div
										class="flex h-5 items-center rounded-full px-2 text-[10px] font-medium text-slate-200 tabular-nums"
										style={`${OVERLAY_TEXT_SHADOW} --_t: '${previewTimeText}';`}
									>
										{previewTimeText}
									</div>
								</div>
							{/key}
						</div>
						<div class="relative h-1.5">
							<div class="absolute inset-0 rounded-full bg-black/35"></div>
							<div
								class="absolute inset-y-0 left-0 rounded-l-full bg-white/40 {seekLimitProgress >=
								100
									? 'rounded-r-full'
									: ''}"
								style="width: {seekLimitProgress}%;"
							></div>
							<div
								class="absolute inset-y-0 left-0 rounded-l-full bg-gradient-to-r from-indigo-950 to-indigo-700 {progress >=
								100
									? 'rounded-r-full'
									: ''}"
								style="width: {progress}%;"
							></div>
							{#if seekPreviewVisible && !draggingSeek && hoverPercent > progress && hoverPercent <= seekLimitProgress}
								<div
									class="absolute inset-y-0 z-10 bg-white/50 transition-opacity duration-200 ease-out"
									style="left: {progress}%; width: {Math.min(hoverPercent, seekLimitProgress) -
										progress}%; opacity: 1;"
								></div>
							{/if}
							<div
								class="absolute top-1/2 z-10 size-3 rounded-md bg-indigo-950 transition-transform duration-100 ease-linear"
								style="left: {progress}%; transform: translate(-50%, -50%) scale({seekBarActive
									? 1.5
									: 1});"
							></div>
							{#if durationMs > 0}
								{#each questionMarkers as marker (marker.id)}
									{@const position = clamp((marker.offsetMs / durationMs) * 100, 0, 100)}
									<div
										class={`pointer-events-none absolute top-1/2 h-4 w-0.5 -translate-x-1/2 -translate-y-1/2 rounded-full transition-opacity duration-200 ease-out ${markerTickClass(marker.state)}`}
										style="left: {position}%; opacity: {knowledgeChecksVisible ? 1 : 0};"
									></div>
								{/each}
							{/if}
							{#if seekLimitProgress < 100}
								<div
									class="absolute top-1/2 h-2.5 w-px -translate-x-1/2 -translate-y-1/2 rounded-full bg-white/65"
									style="left: {seekLimitProgress}%;"
								></div>
							{/if}
						</div>
					</div>
					<div class="relative mt-1.5 flex items-center gap-2">
						<div
							class="shrink-0 rounded-full bg-black/30 p-1 {questionPendingControls
								? 'pointer-events-none invisible'
								: 'pointer-events-auto'}"
						>
							<button
								class="flex h-8 w-8 items-center justify-center rounded-full text-white hover:bg-white/10"
								style="transition: background-color 0.2s;"
								onclick={(e: MouseEvent) => {
									e.stopPropagation();
									togglePlayPause();
								}}
								aria-label={paused ? 'Play' : 'Pause'}
							>
								{#if paused}
									<PlaySolid class="size-6 translate-x-px text-white" />
								{:else}
									<PauseSolid class="size-6 text-white" />
								{/if}
							</button>
						</div>
						<!-- svelte-ignore a11y_no_static_element_interactions -->
						<div
							class="relative shrink-0 rounded-full bg-black/30 p-1 {questionPendingControls
								? 'pointer-events-none invisible'
								: 'pointer-events-auto'}"
							onmouseenter={() => {
								showVolumeSlider = true;
								if (volumeHideTimeout) clearTimeout(volumeHideTimeout);
							}}
							onmouseleave={() => {
								scheduleVolumeHide();
							}}
							onclick={(e: MouseEvent) => e.stopPropagation()}
						>
							<div
								class="flex h-8 items-center rounded-full transition-colors duration-200 ease-out hover:bg-white/10"
							>
								<button
									class="flex h-8 w-8 shrink-0 items-center justify-center text-white"
									onclick={(e: MouseEvent) => {
										e.stopPropagation();
										toggleMute();
									}}
									aria-label={muted || volume === 0 ? 'Unmute (m)' : 'Mute (m)'}
								>
									{#if muted || volume === 0}
										<VolumeMuteSolid class="size-5 text-white" />
									{:else if volume < 0.5}
										<VolumeDownSolid class="size-5 text-white" />
									{:else}
										<VolumeUpSolid class="size-5 text-white" />
									{/if}
								</button>
								<div
									class="flex h-8 items-center overflow-hidden transition-all duration-200 ease-out"
									style="width: {showVolumeSlider || draggingVolume
										? `${VOLUME_SLIDER_EXPANDED_WIDTH_PX}px`
										: '0px'};"
								>
									<div
										class="relative mr-3 h-8 w-16 cursor-pointer"
										role="slider"
										aria-label="Volume"
										aria-valuemin={0}
										aria-valuemax={100}
										aria-valuenow={Math.round(effectiveVolume * 100)}
										tabindex={0}
										onpointerdown={handleVolumePointerDown}
										onpointermove={handleVolumePointerMove}
										onpointerup={handleVolumePointerUp}
									>
										<div
											class="absolute top-1/2 h-1 -translate-y-1/2 rounded-full bg-white/25"
											style="left: {VOLUME_SLIDER_PADDING_PX}px; right: {VOLUME_SLIDER_PADDING_PX}px;"
										></div>
										<div
											class="absolute top-1/2 h-1 -translate-y-1/2 rounded-full bg-white"
											style="left: {VOLUME_SLIDER_PADDING_PX}px; width: {effectiveVolume *
												VOLUME_SLIDER_TRACK_WIDTH_PX}px;"
										></div>
										<div
											class="absolute top-1/2 rounded-full bg-white"
											style="left: {VOLUME_SLIDER_PADDING_PX +
												effectiveVolume *
													VOLUME_SLIDER_TRACK_WIDTH_PX}px; width: 10px; height: 10px; transform: translate(-50%, -50%);"
										></div>
									</div>
								</div>
							</div>
						</div>
						<div
							class="shrink-0 rounded-full bg-black/30 p-1 {questionPendingControls
								? 'pointer-events-none invisible'
								: 'pointer-events-auto'}"
						>
							<button
								class="flex h-8 items-center rounded-full px-3 text-sm font-medium text-white tabular-nums hover:bg-white/10"
								style={`transition: background-color 0.2s; ${OVERLAY_TEXT_SHADOW}`}
								onclick={(e: MouseEvent) => {
									e.stopPropagation();
									showRemainingTime = !showRemainingTime;
								}}
								aria-label="Toggle remaining time"
							>
								{timeReadoutText}
							</button>
						</div>
					</div>
				</div>
			</div>
		</div>
	{/if}
</div>
