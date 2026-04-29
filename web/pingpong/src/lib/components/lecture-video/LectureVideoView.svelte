<script module lang="ts">
	export type LectureVideoViewHandle = {
		pauseForChatSubmit: () => Promise<void>;
		continueWatchingAfterChat: () => Promise<boolean>;
	};
</script>

<script lang="ts">
	import { browser } from '$app/environment';
	import { beforeNavigate } from '$app/navigation';
	import type { Snippet } from 'svelte';
	import { createEventDispatcher } from 'svelte';
	import { onMount } from 'svelte';
	import { SvelteMap, SvelteSet } from 'svelte/reactivity';
	import * as api from '$lib/api';
	import type {
		LectureVideoSession,
		LectureVideoSessionState,
		LectureVideoQuestionPrompt,
		LectureVideoQuestionMarker,
		LectureVideoContinuation,
		LectureVideoInteractionHistoryItem
	} from '$lib/api';
	import { hasVisiblePostAnswerFeedback } from '$lib/lectureVideoFeedback';
	import { mergeQuestionOptions } from '$lib/utils/lecture-video';
	import LectureVideoPlayer from './LectureVideoPlayer.svelte';
	import LectureVideoQuestionGallery from './LectureVideoQuestionGallery.svelte';
	import LectureVideoCompletedView from './LectureVideoCompletedView.svelte';

	type QuestionMarkerState = 'upcoming' | 'correct' | 'incorrect';
	type QuestionPresentationRollbackState = {
		questionId: number;
		sessionState: LectureVideoSessionState;
		subtitleText: string | null;
		offsetMs: number;
		shouldResumePlayback: boolean;
	};
	const MSG_LESSON_UPDATED = 'This video lesson was updated. Start a new lesson to continue.';
	const ERROR_CONTROLLER_LEASE_EXPIRED = 'controller_lease_expired';
	const CONTROL_RECOVERY_GRACE_MS = 1_000;
	const ACTIVE_PAGE_RECOVERY_DEBOUNCE_MS = 150;
	type InitErrorAction = 'refresh' | null;
	type InitErrorState = {
		detail: string;
		action: InitErrorAction;
	};
	type LectureVideoSessionRefreshResult = 'refreshed' | 'lesson_updated' | 'failed';

	let {
		classId,
		threadId,
		lectureVideoSrc,
		title = 'Lecture Video',
		canParticipate = true,
		showRefreshAction = true,
		initialSession = null,
		chatAvailable = false,
		playerVolume = $bindable(1),
		chat = undefined
	}: {
		classId: number;
		threadId: number;
		lectureVideoSrc: string;
		title?: string;
		canParticipate?: boolean;
		showRefreshAction?: boolean;
		initialSession?: LectureVideoSession | null;
		chatAvailable?: boolean;
		playerVolume?: number;
		chat?: Snippet;
	} = $props();
	const dispatch = createEventDispatcher<{
		sessionchange: LectureVideoSession;
		playbackresumed: void;
		lessonupdated: void;
	}>();

	// --- Session state ---
	let controllerSessionId: string | null = $state(null);
	let controllerLeaseObservedAtMs: number | null = $state(null);
	let controllerLeaseDurationMs: number | null = $state(null);
	let sessionState: LectureVideoSessionState = $state('playing');
	let stateVersion: number = $state(1);
	let currentQuestion: LectureVideoQuestionPrompt | null = $state(null);
	let currentContinuation: LectureVideoContinuation | null = $state(null);
	let answeredQuestions = new SvelteMap<
		number,
		{
			selectedOptionId: number;
			correctOptionId: number | null;
			options: { id: number; option_text: string; post_answer_text?: string | null }[];
			postAnswerText: string | null;
		}
	>();
	let allQuestions: { id: number; position: number; questionText: string; stopOffsetMs: number }[] =
		$state([]);
	let sessionQuestionMarkers: LectureVideoQuestionMarker[] = $state([]);

	// --- Player state ---
	let videoElement: HTMLVideoElement | null = $state(null);
	let currentTimeMs: number = $state(0);
	let paused: boolean = $state(true);
	let subtitleText: string | null = $state(null);
	let playerDisabled: boolean = $state(false);
	let questionPlaybackLocked: boolean = $state(false);
	let furthestOffsetMs: number = $state(0);
	let initialStartOffsetMs: number = $state(0);
	let videoReadyForPlayback: boolean = $state(false);
	let introNarrationPending: boolean = $state(false);
	let postAnswerNarrationPending: boolean = $state(false);

	// --- UI state ---
	let scrollToQuestionId: number | null = $state(null);
	let isDesktopLayout: boolean = $state(false);
	let activeMobilePanel: 'checks' | 'chat' | null = $state('checks');
	let historyLoaded: boolean = $state(false);
	let historyInteractions: LectureVideoInteractionHistoryItem[] = $state([]);
	let initError = $state<InitErrorState | null>(null);
	let sessionCleanupInFlight = false;

	// Tracks which question we have already posted question_presented for
	// to avoid duplicate posts.
	let questionPresentedForId: number | null = $state(null);

	// When resuming mid-session, seek video to this offset once it can play.
	let resumeOffsetOnCanPlay: number | null = $state(null);

	// Flag to suppress sending video_paused interaction for system-initiated pauses
	// (e.g. auto-pause at question timestamps).
	let suppressPauseInteraction = false;
	let suppressPlayInteraction = false;
	let ignorePauseEventUntilMs = 0;
	let playbackInteractionInFlight = false;
	let playbackSessionRefreshController: AbortController | null = null;
	// Playback pause/resume is latest-state telemetry, not a lossless event log.
	// While a sync is in flight, keep only the newest desired browser playback state.
	let latestPlaybackInteraction: {
		type: 'video_paused' | 'video_resumed';
		offsetMs: number;
	} | null = null;

	// --- Lease renewal ---
	let leaseInterval: ReturnType<typeof setInterval> | null = null;
	const narrationAudioSrcById = new SvelteMap<number, Promise<string>>();
	const narrationObjectUrls = new SvelteSet<string>();
	const resolvedNarrationAudioSrcById = new SvelteMap<number, string>();
	let pendingNarrationCleanup: (() => void) | null = null;
	let pendingNarrationCompletion: (() => void) | null = null;
	let pendingNarrationChatAbort: (() => void) | null = null;
	let currentNarrationAudio: HTMLAudioElement | null = null;
	let narrationPlaybackGeneration = 0;
	let pendingVideoRetryCleanup: (() => void) | null = null;
	let manualPlaybackTarget: 'video' | 'narration' | null = $state(null);
	let autoContinueInFlight = $state(false);
	let autoContinueFailed = $state(false);
	let expiredControlRecoveryInFlight = $state(false);
	let controllerAcquireInFlight = $state(false);
	let acquireControllerSessionInFlight: Promise<LectureVideoSession | null> | null = null;
	let controllerAcquireGeneration = 0;
	let activePageRecoveryTimer: ReturnType<typeof setTimeout> | null = null;
	let initErrorCanRefresh = $derived(showRefreshAction && initError?.action === 'refresh');
	function shouldShowContinuePrompt(): boolean {
		return (
			(sessionState === 'awaiting_post_answer_resume' &&
				!postAnswerNarrationPending &&
				!autoContinueInFlight &&
				hasVisiblePostAnswerFeedback(currentContinuation)) ||
			autoContinueFailed
		);
	}

	let continuePromptProps = $derived({
		showContinue: shouldShowContinuePrompt(),
		continueDisabled: !canParticipate || postAnswerNarrationPending || autoContinueInFlight,
		oncontinue: requestContinue
	});

	function hasVisibleQuestionPrompt(state: LectureVideoSessionState): boolean {
		return state === 'awaiting_answer' || state === 'awaiting_post_answer_resume';
	}

	function isCompletedSession(state: LectureVideoSessionState): boolean {
		return state === 'completed';
	}

	function isDefinedNumber(id: number | null | undefined): id is number {
		return id != null;
	}

	function getActiveQuestionIds(
		locked: boolean,
		question: LectureVideoQuestionPrompt | null,
		continuation: LectureVideoContinuation | null
	): number[] | null {
		if (!locked || !question) {
			return null;
		}

		return [question.id, continuation?.next_question?.id].filter(isDefinedNumber);
	}

	// --- Derived ---
	let questionMarkers = $derived.by(() => {
		const markerOffsets = new SvelteMap<number, number>();
		for (const marker of sessionQuestionMarkers) {
			markerOffsets.set(marker.id, marker.stop_offset_ms);
		}
		for (const question of allQuestions) {
			markerOffsets.set(question.id, question.stopOffsetMs);
		}

		return [...markerOffsets]
			.sort((a, b) => a[1] - b[1])
			.map(([id, offsetMs]) => {
				const answer = answeredQuestions.get(id);
				const state: QuestionMarkerState =
					answer == null
						? 'upcoming'
						: answer.correctOptionId != null && answer.selectedOptionId === answer.correctOptionId
							? 'correct'
							: 'incorrect';
				return {
					id,
					offsetMs,
					label: 'Comprehension Check',
					state
				};
			});
	});
	let playbackLocked = $derived(playerDisabled || questionPlaybackLocked);
	let hasQuestionPrompt = $derived(hasVisibleQuestionPrompt(sessionState));
	let isCompleted = $derived(isCompletedSession(sessionState));
	let visibleCurrentQuestion = $derived(hasQuestionPrompt ? currentQuestion : null);
	let hasMobileChecksPanel = $derived(true);
	let hasMobileChatPanel = $derived(chatAvailable);
	let activeQuestionIds = $derived(
		getActiveQuestionIds(questionPlaybackLocked, currentQuestion, currentContinuation)
	);
	let playbackRequiresManualStart = $derived(
		canParticipate &&
			(manualPlaybackTarget != null ||
				(!controllerSessionId &&
					!controllerAcquireInFlight &&
					!expiredControlRecoveryInFlight &&
					videoReadyForPlayback &&
					paused &&
					sessionState === 'playing' &&
					!playbackLocked))
	);

	function appendAnswerToHistory(
		question: NonNullable<typeof currentQuestion>,
		selectedOptionId: number,
		correctOptionId: number | null,
		postAnswerText: string | null
	) {
		const eventIndex = (historyInteractions.at(-1)?.event_index ?? 0) + 1;
		historyInteractions = [
			...historyInteractions,
			{
				event_index: eventIndex,
				event_type: 'answer_submitted',
				actor_name: 'Me',
				question_id: question.id,
				question_text: question.question_text,
				question_options: question.options.map((option) => ({
					id: option.id,
					option_text: option.option_text,
					post_answer_text:
						option.id === selectedOptionId
							? (option.post_answer_text ?? postAnswerText ?? null)
							: null
				})),
				correct_option_id: correctOptionId,
				option_id: selectedOptionId,
				option_text:
					question.options.find((option) => option.id === selectedOptionId)?.option_text ?? null,
				offset_ms: null,
				from_offset_ms: null,
				to_offset_ms: null,
				created: new Date().toISOString()
			}
		];
	}

	function isVideoAtEnd(media: HTMLVideoElement | null = videoElement): boolean {
		return !!(
			media &&
			(media.ended ||
				(Number.isFinite(media.duration) &&
					media.duration > 0 &&
					media.currentTime >= media.duration - 0.05))
		);
	}

	function stopNarrationPlayback() {
		narrationPlaybackGeneration += 1;
		pendingNarrationCleanup?.();
		pendingNarrationCleanup = null;
		currentNarrationAudio?.pause();
		currentNarrationAudio = null;
	}

	function completePendingNarration() {
		const complete = pendingNarrationCompletion;
		pendingNarrationCompletion = null;
		pendingNarrationChatAbort = null;
		complete?.();
	}

	function cancelPendingNarration() {
		stopNarrationPlayback();
		pendingNarrationCompletion = null;
		pendingNarrationChatAbort = null;
	}

	function abortNarrationPlaybackForChatSubmit() {
		stopNarrationPlayback();
		const abort = pendingNarrationChatAbort ?? pendingNarrationCompletion;
		pendingNarrationCompletion = null;
		pendingNarrationChatAbort = null;
		abort?.();
		clearPendingVideoRetry();
	}

	function trackQuestion(
		question: Pick<LectureVideoQuestionPrompt, 'id' | 'question_text' | 'stop_offset_ms'> | null
	) {
		if (!question || allQuestions.some(({ id }) => id === question.id)) {
			return;
		}

		allQuestions = [
			...allQuestions,
			{
				id: question.id,
				position: allQuestions.length + 1,
				questionText: question.question_text,
				stopOffsetMs: question.stop_offset_ms
			}
		];
	}

	function clearQuestionScrollTarget() {
		scrollToQuestionId = null;
	}

	$effect(() => {
		if (playbackLocked && videoElement && !videoElement.paused) {
			suppressPauseInteraction = true;
			videoElement.pause();
		}
	});

	$effect(() => {
		applyPendingResumeOffset();
	});

	$effect(() => {
		if (currentNarrationAudio) {
			currentNarrationAudio.volume = playerVolume;
		}
	});

	$effect(() => {
		if (sessionState !== 'completed' || !leaseInterval) return;

		clearInterval(leaseInterval);
		leaseInterval = null;
	});

	// =========================================================================
	// Lifecycle
	// =========================================================================

	onMount(() => {
		void initSession();
		window.addEventListener('beforeunload', handleBeforeUnload);
		const handleActivePageRecovery = (event: Event) => {
			if (document.visibilityState === 'hidden') return;
			const force =
				event.type === 'pageshow' &&
				'persisted' in event &&
				(event as PageTransitionEvent).persisted === true;
			scheduleActivePageRecovery({ force });
		};
		document.addEventListener('visibilitychange', handleActivePageRecovery);
		window.addEventListener('pageshow', handleActivePageRecovery);
		window.addEventListener('focus', handleActivePageRecovery);

		return () => {
			if (activePageRecoveryTimer) {
				clearTimeout(activePageRecoveryTimer);
				activePageRecoveryTimer = null;
			}
			window.removeEventListener('beforeunload', handleBeforeUnload);
			document.removeEventListener('visibilitychange', handleActivePageRecovery);
			window.removeEventListener('pageshow', handleActivePageRecovery);
			window.removeEventListener('focus', handleActivePageRecovery);
			void cleanupLectureVideoSession({ postPause: true, releaseControl: true });
			revokeNarrationResources();
		};
	});

	beforeNavigate(() => {
		void cleanupLectureVideoSession({ postPause: true, releaseControl: true });
	});

	$effect(() => {
		if (!browser) return;

		const mediaQuery = window.matchMedia('(min-width: 1280px)');
		const updateLayout = () => {
			isDesktopLayout = mediaQuery.matches;
		};

		updateLayout();
		mediaQuery.addEventListener('change', updateLayout);

		return () => {
			mediaQuery.removeEventListener('change', updateLayout);
		};
	});

	$effect(() => {
		if (hasQuestionPrompt && hasMobileChecksPanel) {
			activeMobilePanel = 'checks';
			return;
		}
		if (hasMobileChatPanel) {
			activeMobilePanel = 'chat';
			return;
		}
		activeMobilePanel = hasMobileChecksPanel ? 'checks' : hasMobileChatPanel ? 'chat' : null;
	});

	function mobileSegmentClass(panel: 'checks' | 'chat'): string {
		return `rounded-xl px-4 py-1 text-sm font-medium transition-colors ${
			activeMobilePanel === panel
				? 'bg-white text-slate-950 shadow-sm'
				: 'text-slate-600 hover:text-slate-900'
		}`;
	}

	// =========================================================================
	// Session helpers
	// =========================================================================

	function resetState() {
		controllerSessionId = null;
		clearControllerLease();
		sessionState = 'playing';
		stateVersion = 1;
		currentQuestion = null;
		currentContinuation = null;
		answeredQuestions.clear();
		allQuestions = [];
		sessionQuestionMarkers = [];
		currentTimeMs = 0;
		paused = true;
		subtitleText = null;
		playerDisabled = false;
		questionPlaybackLocked = false;
		furthestOffsetMs = 0;
		initialStartOffsetMs = 0;
		videoReadyForPlayback = false;
		introNarrationPending = false;
		postAnswerNarrationPending = false;
		playerVolume = 1;
		historyLoaded = false;
		historyInteractions = [];
		initError = null;
		questionPresentedForId = null;
		resumeOffsetOnCanPlay = null;
		suppressPauseInteraction = false;
		suppressPlayInteraction = false;
		ignorePauseEventUntilMs = 0;
		playbackInteractionInFlight = false;
		playbackSessionRefreshController?.abort();
		playbackSessionRefreshController = null;
		latestPlaybackInteraction = null;
		revokeNarrationResources();
		clearPendingVideoRetry();
		autoContinueInFlight = false;
		autoContinueFailed = false;
		expiredControlRecoveryInFlight = false;
		controllerAcquireInFlight = false;
		acquireControllerSessionInFlight = null;
		controllerAcquireGeneration += 1;
		if (activePageRecoveryTimer) {
			clearTimeout(activePageRecoveryTimer);
			activePageRecoveryTimer = null;
		}
	}

	function clearControllerLease() {
		controllerLeaseObservedAtMs = null;
		controllerLeaseDurationMs = null;
	}

	function setControllerLease(leaseDurationMs?: number | null) {
		if (leaseDurationMs != null && leaseDurationMs > 0) {
			controllerLeaseObservedAtMs = Date.now();
			controllerLeaseDurationMs = leaseDurationMs;
			return;
		}

		controllerLeaseObservedAtMs = null;
		controllerLeaseDurationMs = null;
	}

	function scheduleActivePageRecovery({ force = false }: { force?: boolean } = {}) {
		if (activePageRecoveryTimer) {
			clearTimeout(activePageRecoveryTimer);
		}
		activePageRecoveryTimer = setTimeout(() => {
			activePageRecoveryTimer = null;
			void recoverExpiredControl({ force });
		}, ACTIVE_PAGE_RECOVERY_DEBOUNCE_MS);
	}

	function revokeNarrationResources() {
		for (const objectUrl of narrationObjectUrls) {
			URL.revokeObjectURL(objectUrl);
		}
		narrationObjectUrls.clear();
		narrationAudioSrcById.clear();
		resolvedNarrationAudioSrcById.clear();
		cancelPendingNarration();
	}

	function clearPendingVideoRetry() {
		pendingVideoRetryCleanup?.();
		pendingVideoRetryCleanup = null;
		manualPlaybackTarget = null;
	}

	function maybeAutoContinueAfterPostAnswer() {
		void requestContinue();
	}

	function pausePostAnswerNarrationForChatSubmit() {
		postAnswerNarrationPending = false;
		if (!hasVisiblePostAnswerFeedback(currentContinuation)) {
			autoContinueFailed = true;
		}
	}

	function queueVideoRetry() {
		manualPlaybackTarget = 'video';
	}

	function queueNarrationRetry() {
		manualPlaybackTarget = 'narration';
	}

	async function refreshLesson() {
		if (!browser) return;
		await initSession();
	}

	function actionForErrorResponse(
		status: number,
		detail?: string | null,
		defaultAction: InitErrorAction = 'refresh'
	): InitErrorAction {
		if (detail === MSG_LESSON_UPDATED) {
			return null;
		}
		if (status === 409) {
			return 'refresh';
		}
		if (status === 422) {
			return null;
		}
		return defaultAction;
	}

	function setInitError(detail: string, action: InitErrorAction) {
		initError = { detail, action };
		if (detail === MSG_LESSON_UPDATED) {
			dispatch('lessonupdated');
		}
	}

	function failClosedControl(
		detail?: string | null,
		{ action }: { action?: InitErrorAction } = {}
	) {
		if (leaseInterval) {
			clearInterval(leaseInterval);
			leaseInterval = null;
		}

		clearPendingVideoRetry();
		resumeOffsetOnCanPlay = null;
		cancelPendingNarration();
		autoContinueInFlight = false;
		playbackSessionRefreshController?.abort();
		playbackSessionRefreshController = null;
		latestPlaybackInteraction = null;

		if (videoElement && !videoElement.paused) {
			suppressPauseInteraction = true;
			videoElement.pause();
		}

		controllerSessionId = null;
		clearControllerLease();
		playerDisabled = true;
		const resolvedDetail =
			detail ||
			'The video stopped because this tab is no longer connected. Refresh the lesson to continue.';
		setInitError(
			resolvedDetail,
			action ?? (resolvedDetail === MSG_LESSON_UPDATED ? null : 'refresh')
		);
	}

	function failClosedOnConflict(expanded: {
		$status: number;
		error: { detail?: string; error_code?: string } | null;
	}): boolean {
		if (expanded.$status !== 409) {
			return false;
		}

		failClosedControl(expanded.error?.detail, {
			action: actionForErrorResponse(expanded.$status, expanded.error?.detail)
		});
		return true;
	}

	function isControllerLeaseExpiredError(expanded: {
		$status: number;
		error: { error_code?: string } | null;
	}): boolean {
		return (
			expanded.$status === 409 && expanded.error?.error_code === ERROR_CONTROLLER_LEASE_EXPIRED
		);
	}

	async function refreshLectureVideoSession(
		controllerSessionIdForRequest: string
	): Promise<LectureVideoSessionRefreshResult> {
		playbackSessionRefreshController?.abort();
		const refreshController = new AbortController();
		playbackSessionRefreshController = refreshController;
		try {
			const response = await api.getThread(
				fetch,
				classId,
				threadId,
				controllerSessionIdForRequest,
				refreshController.signal
			);
			if (
				refreshController.signal.aborted ||
				controllerSessionId !== controllerSessionIdForRequest
			) {
				return 'failed';
			}

			const expanded = api.expandResponse(response);
			if (expanded.error) {
				return 'failed';
			}
			if (expanded.data.lecture_video_matches_assistant === false) {
				failClosedControl(MSG_LESSON_UPDATED, { action: null });
				return 'lesson_updated';
			}

			const refreshedSession = expanded.data.lecture_video_session;
			if (!refreshedSession) {
				return 'failed';
			}

			applySession(refreshedSession);
			return 'refreshed';
		} catch (error) {
			if (error instanceof DOMException && error.name === 'AbortError') {
				return 'failed';
			}
			return 'failed';
		} finally {
			if (playbackSessionRefreshController === refreshController) {
				playbackSessionRefreshController = null;
			}
		}
	}

	function queuePlaybackInteraction(type: 'video_paused' | 'video_resumed') {
		if (!controllerSessionId || sessionState !== 'playing') {
			return;
		}

		latestPlaybackInteraction = {
			type,
			offsetMs: Math.round(currentTimeMs)
		};

		if (!playbackInteractionInFlight) {
			void drainPlaybackInteractionQueue();
		}
	}

	async function drainPlaybackInteractionQueue() {
		if (playbackInteractionInFlight) {
			return;
		}

		playbackInteractionInFlight = true;
		try {
			while (latestPlaybackInteraction) {
				const interaction = latestPlaybackInteraction;
				latestPlaybackInteraction = null;

				const interactionControllerSessionId = controllerSessionId;
				if (!interactionControllerSessionId || sessionState !== 'playing') {
					// Playback telemetry is only meaningful while video playback is active.
					// If the session moved into a question/completion state, drop the stale desired state.
					return;
				}

				try {
					const response = await api.postLectureVideoInteraction(fetch, classId, threadId, {
						type: interaction.type,
						controller_session_id: interactionControllerSessionId,
						expected_state_version: stateVersion,
						idempotency_key: crypto.randomUUID(),
						offset_ms: interaction.offsetMs
					});
					if (controllerSessionId !== interactionControllerSessionId) {
						return;
					}

					const expanded = api.expandResponse(response);
					if (expanded.$status === 409) {
						if (expanded.error?.detail === MSG_LESSON_UPDATED) {
							failClosedControl(expanded.error.detail, { action: null });
							return;
						}
						const refreshResult = await refreshLectureVideoSession(interactionControllerSessionId);
						if (refreshResult === 'lesson_updated') {
							return;
						}
						if (refreshResult === 'failed') {
							if (controllerSessionId !== interactionControllerSessionId) {
								return;
							}
							failClosedControl(
								'This lesson changed while you were watching. Refresh the lesson to continue.'
							);
							return;
						}
						continue;
					}
					if (expanded.error) {
						failClosedControl(
							expanded.error.detail ||
								'We could not save your video progress. Refresh the lesson to continue.',
							{
								action: actionForErrorResponse(expanded.$status, expanded.error.detail)
							}
						);
						return;
					}

					applySession(expanded.data.lecture_video_session);
				} catch (error) {
					if (controllerSessionId !== interactionControllerSessionId) {
						return;
					}
					failClosedControl(error instanceof Error ? error.message : String(error));
					return;
				}
			}
		} finally {
			playbackInteractionInFlight = false;
			if (latestPlaybackInteraction) {
				// A new desired playback state may arrive while an earlier attempt exits early.
				// Restart once after releasing the in-flight guard so that latest state is not stranded.
				void drainPlaybackInteractionQueue();
			}
		}
	}

	async function tryPlayVideo({
		suppressInteractionPost = false,
		queueRetryOnFailure = false
	}: {
		suppressInteractionPost?: boolean;
		queueRetryOnFailure?: boolean;
	} = {}): Promise<boolean> {
		if (!videoElement) {
			return false;
		}

		if (suppressInteractionPost) {
			suppressPlayInteraction = true;
		}

		try {
			await videoElement.play();
			clearPendingVideoRetry();
			return true;
		} catch {
			if (suppressInteractionPost) {
				suppressPlayInteraction = false;
			}
			ignorePauseEventUntilMs =
				(typeof performance !== 'undefined' ? performance.now() : Date.now()) + 500;
			if (queueRetryOnFailure) {
				queueVideoRetry();
			}
			return false;
		}
	}

	async function acquireControllerSession(): Promise<LectureVideoSession | null> {
		if (acquireControllerSessionInFlight) {
			return await acquireControllerSessionInFlight;
		}

		const acquireGeneration = controllerAcquireGeneration;
		const acquirePromise = (async () => {
			controllerAcquireInFlight = true;
			try {
				const response = await api.acquireLectureVideoControl(fetch, classId, threadId);
				const expanded = api.expandResponse(response);
				if (acquireGeneration !== controllerAcquireGeneration) {
					return null;
				}
				if (expanded.error) {
					failClosedControl(expanded.error.detail, {
						action: actionForErrorResponse(expanded.$status, expanded.error.detail)
					});
					return null;
				}

				controllerSessionId = expanded.data.controller_session_id;
				applySession(expanded.data.lecture_video_session);
				return expanded.data.lecture_video_session;
			} catch (error) {
				if (acquireGeneration !== controllerAcquireGeneration) {
					return null;
				}
				failClosedControl(error instanceof Error ? error.message : String(error));
				return null;
			}
		})();
		acquireControllerSessionInFlight = acquirePromise;
		try {
			return await acquirePromise;
		} finally {
			if (acquireControllerSessionInFlight === acquirePromise) {
				acquireControllerSessionInFlight = null;
				controllerAcquireInFlight = false;
			}
		}
	}

	async function ensureControllerSession(): Promise<boolean> {
		if (controllerSessionId) {
			return true;
		}

		return (await acquireControllerSession()) != null;
	}

	function hasExpiredControllerLease(): boolean {
		return (
			controllerSessionId != null &&
			controllerLeaseObservedAtMs != null &&
			controllerLeaseDurationMs != null &&
			Date.now() >=
				controllerLeaseObservedAtMs + controllerLeaseDurationMs - CONTROL_RECOVERY_GRACE_MS
		);
	}

	async function recoverExpiredControl({ force = false }: { force?: boolean } = {}) {
		if (
			!browser ||
			!canParticipate ||
			sessionCleanupInFlight ||
			expiredControlRecoveryInFlight ||
			(!force && !hasExpiredControllerLease()) ||
			!controllerSessionId
		) {
			return;
		}

		expiredControlRecoveryInFlight = true;
		const shouldResumePlayback = sessionState === 'playing' && !playbackLocked && !isVideoAtEnd();
		controllerSessionId = null;
		clearControllerLease();
		latestPlaybackInteraction = null;
		playbackSessionRefreshController?.abort();
		playbackSessionRefreshController = null;

		try {
			const session = await acquireControllerSession();
			if (!session) {
				return;
			}

			if (session.last_known_offset_ms != null && session.last_known_offset_ms > 0) {
				resumeOffsetOnCanPlay = session.last_known_offset_ms;
				applyPendingResumeOffset();
			}
			if (
				shouldResumePlayback &&
				session.state === 'playing' &&
				!playbackLocked &&
				!isVideoAtEnd()
			) {
				queueVideoRetry();
			}
		} finally {
			expiredControlRecoveryInFlight = false;
		}
	}

	async function cleanupLectureVideoSession({
		postPause,
		releaseControl
	}: {
		postPause: boolean;
		releaseControl: boolean;
	}) {
		if (sessionCleanupInFlight) return;

		const cleanupSessionId = controllerSessionId;
		if (!cleanupSessionId) return;

		sessionCleanupInFlight = true;

		if (leaseInterval) {
			clearInterval(leaseInterval);
			leaseInterval = null;
		}

		cancelPendingNarration();
		clearPendingVideoRetry();

		if (videoElement && !videoElement.paused) {
			suppressPauseInteraction = true;
			videoElement.pause();
		}

		const shouldPostPause =
			postPause && sessionState === 'playing' && !playbackLocked && !isVideoAtEnd();

		try {
			if (shouldPostPause) {
				const response = await api.postLectureVideoInteraction(fetch, classId, threadId, {
					type: 'video_paused',
					controller_session_id: cleanupSessionId,
					expected_state_version: stateVersion,
					idempotency_key: crypto.randomUUID(),
					offset_ms: Math.round(currentTimeMs)
				});
				const expanded = api.expandResponse(response);
				if (!expanded.error) {
					applySession(expanded.data.lecture_video_session);
				}
			}
		} catch {
			// Best-effort cleanup during navigation/unload.
		}

		try {
			if (releaseControl) {
				await api.releaseLectureVideoControl(fetch, classId, threadId, cleanupSessionId);
			}
		} catch {
			// Best-effort cleanup during navigation/unload.
		} finally {
			if (controllerSessionId === cleanupSessionId) {
				controllerSessionId = null;
				clearControllerLease();
			}
			sessionCleanupInFlight = false;
		}
	}

	async function initSession() {
		resetState();

		const interactions = await reconstructFromHistory();
		historyInteractions = interactions;
		historyLoaded = true;
		if (!canParticipate) {
			if (initialSession) {
				applySession(initialSession);
				initialStartOffsetMs = initialSession.last_known_offset_ms ?? 0;
				if (sessionState === 'awaiting_answer' && currentQuestion) {
					questionPresentedForId = currentQuestion.id;
					subtitleText = currentQuestion.intro_text || null;
				}
			}
			return;
		}

		// If resuming mid-session, seek video to last known offset
		const session = await acquireControllerSession();
		if (!session) {
			return;
		}
		initialStartOffsetMs = session.last_known_offset_ms ?? 0;
		if (session.last_known_offset_ms && session.last_known_offset_ms > 0) {
			resumeOffsetOnCanPlay = session.last_known_offset_ms;
		}

		// If resuming mid-question, replay the intro narration
		if (sessionState === 'awaiting_answer' && currentQuestion) {
			questionPresentedForId = currentQuestion.id;
			if (currentQuestion.intro_text) {
				subtitleText = currentQuestion.intro_text;
			}
			if (currentQuestion.intro_narration_id) {
				playerDisabled = true;
				introNarrationPending = true;
				void playNarration(currentQuestion.intro_narration_id, () => {
					playerDisabled = false;
					introNarrationPending = false;
				});
			}
		}

		if (
			sessionState === 'awaiting_post_answer_resume' &&
			currentContinuation?.post_answer_narration_id
		) {
			postAnswerNarrationPending = true;
			void playNarration(
				currentContinuation.post_answer_narration_id,
				() => {
					postAnswerNarrationPending = false;
					maybeAutoContinueAfterPostAnswer();
				},
				pausePostAnswerNarrationForChatSubmit
			);
		} else if (
			sessionState === 'awaiting_post_answer_resume' &&
			!hasVisiblePostAnswerFeedback(currentContinuation)
		) {
			maybeAutoContinueAfterPostAnswer();
		}

		applyPendingResumeOffset();
		if (sessionState === 'playing' && !playbackLocked && !isVideoAtEnd()) {
			queueVideoRetry();
		}

		// Start lease renewal every 20 seconds
		leaseInterval = setInterval(async () => {
			if (!controllerSessionId) return;
			try {
				const renewingControllerSessionId = controllerSessionId;
				const response = await api.renewLectureVideoControl(
					fetch,
					classId,
					threadId,
					renewingControllerSessionId
				);
				const expanded = api.expandResponse(response);
				if (expanded.error) {
					if (isControllerLeaseExpiredError(expanded)) {
						await recoverExpiredControl({ force: true });
						return;
					}
					failClosedControl(expanded.error.detail, {
						action: actionForErrorResponse(expanded.$status, expanded.error.detail)
					});
					return;
				}
				if (controllerSessionId !== renewingControllerSessionId) {
					return;
				}
				setControllerLease(expanded.data.lease_duration_ms);
			} catch (error) {
				failClosedControl(error instanceof Error ? error.message : String(error));
			}
		}, 20_000);
	}

	async function reconstructFromHistory(
		prefetchedInteractions: LectureVideoInteractionHistoryItem[] | null = null
	): Promise<LectureVideoInteractionHistoryItem[]> {
		let interactions = prefetchedInteractions;
		if (interactions == null) {
			const historyResponse = await api.getLectureVideoHistory(fetch, classId, threadId);
			const historyExpanded = api.expandResponse(historyResponse);
			if (historyExpanded.error) {
				setInitError(
					historyExpanded.error.detail ||
						'We could not load your lesson progress. Refresh the lesson and try again.',
					actionForErrorResponse(historyExpanded.$status, historyExpanded.error.detail)
				);
				return [];
			}
			interactions = historyExpanded.data.interactions;
		}

		// Track question_id → question metadata needed to rebuild the sidebar state from history.
		const questionInfo = new SvelteMap<
			number,
			{
				questionText: string;
				stopOffsetMs: number;
				options: { id: number; option_text: string; post_answer_text?: string | null }[];
				correctOptionId: number | null;
			}
		>();
		const answerInfo = new SvelteMap<
			number,
			{ optionId: number; optionText: string; postAnswerText: string | null }
		>();

		for (const item of interactions) {
			if (item.question_id != null) {
				const existingQuestion = questionInfo.get(item.question_id);
				questionInfo.set(item.question_id, {
					questionText: item.question_text ?? existingQuestion?.questionText ?? '',
					stopOffsetMs:
						item.event_type === 'question_presented'
							? (item.offset_ms ?? existingQuestion?.stopOffsetMs ?? 0)
							: (existingQuestion?.stopOffsetMs ?? 0),
					options:
						item.question_options && item.question_options.length > 0
							? mergeQuestionOptions(existingQuestion?.options ?? [], item.question_options)
							: (existingQuestion?.options ?? []),
					correctOptionId: item.correct_option_id ?? existingQuestion?.correctOptionId ?? null
				});
			}
			if (
				item.event_type === 'answer_submitted' &&
				item.question_id != null &&
				item.option_id != null
			) {
				const postAnswerText =
					item.question_options?.find((option) => option.id === item.option_id)?.post_answer_text ??
					questionInfo.get(item.question_id)?.options.find((option) => option.id === item.option_id)
						?.post_answer_text ??
					null;
				answerInfo.set(item.question_id, {
					optionId: item.option_id,
					optionText: item.option_text ?? '',
					postAnswerText
				});
			}
		}

		// Build allQuestions from presented questions (in order)
		let position = 1;
		for (const [qId, info] of questionInfo) {
			if (!allQuestions.find((q) => q.id === qId)) {
				allQuestions = [
					...allQuestions,
					{
						id: qId,
						position: position,
						questionText: info.questionText,
						stopOffsetMs: info.stopOffsetMs
					}
				];
			}
			position++;
		}

		// Build answeredQuestions from answers
		for (const [qId, answer] of answerInfo) {
			if (!answeredQuestions.has(qId)) {
				const question = questionInfo.get(qId);
				answeredQuestions.set(qId, {
					selectedOptionId: answer.optionId,
					correctOptionId: question?.correctOptionId ?? null,
					options: question?.options.length
						? question.options
						: [
								{
									id: answer.optionId,
									option_text: answer.optionText,
									post_answer_text: answer.postAnswerText
								}
							],
					postAnswerText: answer.postAnswerText
				});
			}
		}

		return interactions;
	}

	function applySession(session: LectureVideoSession) {
		sessionState = session.state;
		stateVersion = session.state_version;
		currentQuestion = session.current_question;
		currentContinuation = session.current_continuation;
		sessionQuestionMarkers = session.question_markers ?? [];
		if (session.controller.has_control) {
			setControllerLease(session.controller.lease_duration_ms);
		} else {
			clearControllerLease();
		}
		if (session.state !== 'awaiting_post_answer_resume') {
			autoContinueFailed = false;
		}
		furthestOffsetMs = session.furthest_offset_ms ?? 0;
		questionPlaybackLocked =
			session.state === 'awaiting_answer' || session.state === 'awaiting_post_answer_resume';

		trackQuestion(session.current_question);
		trackQuestion(session.current_continuation?.next_question ?? null);
		dispatch('sessionchange', session);
	}

	export async function pauseForChatSubmit() {
		abortNarrationPlaybackForChatSubmit();

		if (!canParticipate || playbackLocked || sessionState !== 'playing') {
			return;
		}

		if (paused || videoElement?.paused) {
			return;
		}

		videoElement?.pause();

		if (!(await ensureControllerSession())) {
			return;
		}
	}

	export async function continueWatchingAfterChat(): Promise<boolean> {
		if (!canParticipate) {
			return false;
		}

		if (sessionState === 'awaiting_post_answer_resume') {
			return requestContinue();
		}

		if (playbackLocked || sessionState !== 'playing') {
			return false;
		}

		if (videoElement && !videoElement.paused) {
			return true;
		}

		if (!(await ensureControllerSession())) {
			return false;
		}

		return tryPlayVideo({
			suppressInteractionPost: true,
			queueRetryOnFailure: true
		});
	}

	// =========================================================================
	// Video event handlers
	// =========================================================================

	function applyPendingResumeOffset() {
		if (resumeOffsetOnCanPlay == null || !videoElement) return;
		if (videoElement.readyState < HTMLMediaElement.HAVE_METADATA) return;

		setVideoPosition(resumeOffsetOnCanPlay);
		resumeOffsetOnCanPlay = null;
	}

	function setVideoPosition(offsetMs: number) {
		if (!videoElement) return;
		currentTimeMs = offsetMs;
		videoElement.currentTime = offsetMs / 1000;
	}

	async function rollbackQuestionPresentedFailure(
		rollbackState: QuestionPresentationRollbackState
	) {
		if (questionPresentedForId !== rollbackState.questionId) {
			return;
		}

		questionPresentedForId = null;
		questionPlaybackLocked = false;
		suppressPauseInteraction = false;
		playerDisabled = false;
		introNarrationPending = false;
		sessionState = rollbackState.sessionState;
		subtitleText = rollbackState.subtitleText;

		if (!videoElement) {
			return;
		}

		setVideoPosition(rollbackState.offsetMs);
		if (rollbackState.shouldResumePlayback) {
			await tryPlayVideo({
				suppressInteractionPost: true,
				queueRetryOnFailure: true
			});
		}
	}

	function handleCanPlay() {
		applyPendingResumeOffset();
		videoReadyForPlayback = true;
	}

	function handleTimeUpdate() {
		if (sessionState !== 'playing' || !currentQuestion || playerDisabled) return;
		if (answeredQuestions.has(currentQuestion.id)) return;

		if (
			currentTimeMs >= currentQuestion.stop_offset_ms &&
			questionPresentedForId !== currentQuestion.id
		) {
			const rollbackState: QuestionPresentationRollbackState = {
				questionId: currentQuestion.id,
				sessionState,
				subtitleText,
				offsetMs: currentQuestion.stop_offset_ms,
				shouldResumePlayback: !videoElement?.paused
			};

			// Auto-pause at question timestamp (suppress the pause interaction)
			questionPlaybackLocked = true;
			suppressPauseInteraction = true;
			setVideoPosition(currentQuestion.stop_offset_ms);
			videoElement?.pause();
			questionPresentedForId = currentQuestion.id;
			void beginIntroFlow(rollbackState);
		}
	}

	function handlePause() {
		const nowMs = typeof performance !== 'undefined' ? performance.now() : Date.now();
		if (ignorePauseEventUntilMs > nowMs) {
			ignorePauseEventUntilMs = 0;
			return;
		}
		ignorePauseEventUntilMs = 0;
		if (suppressPauseInteraction) {
			suppressPauseInteraction = false;
			return;
		}
		if (isVideoAtEnd()) {
			return;
		}
		if (playbackLocked) return;
		if (!controllerSessionId || sessionState !== 'playing') return;
		queuePlaybackInteraction('video_paused');
	}

	function handlePlay() {
		clearPendingVideoRetry();
		dispatch('playbackresumed');
		if (!videoElement) return;
		if (playbackLocked) {
			suppressPauseInteraction = true;
			videoElement.pause();
			return;
		}
		if (suppressPlayInteraction) {
			suppressPlayInteraction = false;
			return;
		}
		if (!controllerSessionId || sessionState !== 'playing') return;
		queuePlaybackInteraction('video_resumed');
	}

	async function handleSeek(toOffsetMs: number, fromOffsetMs: number) {
		const seekControllerSessionId = controllerSessionId;
		if (!seekControllerSessionId || !videoElement || playbackLocked) return;
		if (toOffsetMs === fromOffsetMs) return;

		const payload = {
			type: 'video_seeked' as const,
			controller_session_id: seekControllerSessionId,
			expected_state_version: stateVersion,
			idempotency_key: crypto.randomUUID(),
			from_offset_ms: fromOffsetMs,
			to_offset_ms: toOffsetMs
		};

		if (currentQuestion && !answeredQuestions.has(currentQuestion.id)) {
			questionPresentedForId =
				toOffsetMs < currentQuestion.stop_offset_ms ? null : questionPresentedForId;
		}

		try {
			const response = await api.postLectureVideoInteraction(fetch, classId, threadId, payload);
			if (controllerSessionId !== seekControllerSessionId) {
				return;
			}
			const expanded = api.expandResponse(response);
			if (failClosedOnConflict(expanded)) {
				return;
			}
			if (!expanded.error) {
				applySession(expanded.data.lecture_video_session);
				return;
			}

			setVideoPosition(fromOffsetMs);
			failClosedControl(
				expanded.error.detail ||
					'We could not save your new video spot. Refresh the lesson to continue.',
				{
					action: actionForErrorResponse(expanded.$status, expanded.error.detail)
				}
			);
		} catch (error) {
			if (controllerSessionId !== seekControllerSessionId) {
				return;
			}
			setVideoPosition(fromOffsetMs);
			failClosedControl(error instanceof Error ? error.message : String(error));
		}
	}

	async function handleVideoEnded() {
		const endedControllerSessionId = controllerSessionId;
		if (!endedControllerSessionId) return;
		try {
			const response = await api.postLectureVideoInteraction(fetch, classId, threadId, {
				type: 'video_ended',
				controller_session_id: endedControllerSessionId,
				expected_state_version: stateVersion,
				idempotency_key: crypto.randomUUID(),
				offset_ms: Math.round(currentTimeMs)
			});
			if (controllerSessionId !== endedControllerSessionId) {
				return;
			}
			const expanded = api.expandResponse(response);
			if (failClosedOnConflict(expanded)) {
				return;
			}
			if (!expanded.error) {
				applySession(expanded.data.lecture_video_session);
				return;
			}

			failClosedControl(
				expanded.error.detail ||
					'We could not mark this lesson complete. Refresh the lesson and try again.',
				{
					action: actionForErrorResponse(expanded.$status, expanded.error.detail)
				}
			);
		} catch (error) {
			if (controllerSessionId !== endedControllerSessionId) {
				return;
			}
			failClosedControl(error instanceof Error ? error.message : String(error));
		}
	}

	// =========================================================================
	// Intro / narration flow
	// =========================================================================

	async function getNarrationAudioSrc(narrationId: number): Promise<string> {
		const cached = narrationAudioSrcById.get(narrationId);
		if (cached) return cached;

		const narrationSrcPromise = (async () => {
			try {
				const narrationUrl = api.lectureVideoNarrationUrl(classId, threadId, narrationId);
				const response = await fetch(narrationUrl);
				if (!response.ok) {
					throw new Error(`Failed to load narration ${narrationId}`);
				}
				const blob = await response.blob();
				const objectUrl = URL.createObjectURL(blob);
				narrationObjectUrls.add(objectUrl);
				resolvedNarrationAudioSrcById.set(narrationId, objectUrl);
				return objectUrl;
			} catch (error) {
				narrationAudioSrcById.delete(narrationId);
				resolvedNarrationAudioSrcById.delete(narrationId);
				throw error;
			}
		})();

		narrationAudioSrcById.set(narrationId, narrationSrcPromise);
		return narrationSrcPromise;
	}

	async function playNarration(
		narrationId: number,
		onComplete: () => void,
		onChatAbort: () => void = onComplete
	) {
		stopNarrationPlayback();
		const playbackGeneration = narrationPlaybackGeneration;
		pendingNarrationCompletion = onComplete;
		pendingNarrationChatAbort = onChatAbort;

		try {
			const narrationSrc = await getNarrationAudioSrc(narrationId);
			if (playbackGeneration !== narrationPlaybackGeneration) {
				return;
			}
			const audio = new Audio(narrationSrc);
			audio.volume = playerVolume;
			currentNarrationAudio = audio;
			audio.addEventListener('ended', () => {
				if (playbackGeneration !== narrationPlaybackGeneration) {
					return;
				}
				if (manualPlaybackTarget === 'narration' && currentNarrationAudio === audio) {
					clearPendingVideoRetry();
				}
				if (currentNarrationAudio === audio) {
					currentNarrationAudio = null;
				}
				completePendingNarration();
			});
			audio.addEventListener('error', () => {
				if (playbackGeneration !== narrationPlaybackGeneration) {
					return;
				}
				if (manualPlaybackTarget === 'narration' && currentNarrationAudio === audio) {
					clearPendingVideoRetry();
				}
				if (currentNarrationAudio === audio) {
					currentNarrationAudio = null;
				}
				completePendingNarration();
			});
			try {
				await audio.play();
				if (playbackGeneration !== narrationPlaybackGeneration) {
					audio.pause();
					return;
				}
				clearPendingVideoRetry();
			} catch {
				if (playbackGeneration !== narrationPlaybackGeneration) {
					return;
				}
				pendingNarrationCleanup = () => {
					audio.pause();
					if (currentNarrationAudio === audio) {
						currentNarrationAudio = null;
					}
				};
				queueNarrationRetry();
			}
		} catch {
			if (playbackGeneration !== narrationPlaybackGeneration) {
				return;
			}
			currentNarrationAudio = null;
			completePendingNarration();
		}
	}

	async function beginIntroFlow(rollbackState?: QuestionPresentationRollbackState) {
		if (!currentQuestion) return;

		// Show intro text as subtitle
		if (currentQuestion.intro_text) {
			subtitleText = currentQuestion.intro_text;
		}

		// Play intro narration if available
		if (currentQuestion.intro_narration_id) {
			playerDisabled = true;
			introNarrationPending = true;
			void playNarration(currentQuestion.intro_narration_id, () => {
				playerDisabled = false;
				introNarrationPending = false;
				void postQuestionPresented(rollbackState);
			});
		} else {
			void postQuestionPresented(rollbackState);
		}
	}

	// =========================================================================
	// Interaction posts
	// =========================================================================

	async function postQuestionPresented(rollbackState?: QuestionPresentationRollbackState) {
		if (!controllerSessionId || !currentQuestion) return;
		try {
			const response = await api.postLectureVideoInteraction(fetch, classId, threadId, {
				type: 'question_presented',
				controller_session_id: controllerSessionId,
				expected_state_version: stateVersion,
				idempotency_key: crypto.randomUUID(),
				question_id: currentQuestion.id,
				offset_ms: currentQuestion.stop_offset_ms
			});
			const expanded = api.expandResponse(response);
			if (failClosedOnConflict(expanded)) {
				return;
			}
			if (!expanded.error) {
				applySession(expanded.data.lecture_video_session);
				return;
			}
		} catch {
			// Roll back optimistic question-presentation UI on non-conflict failures.
		}

		if (rollbackState) {
			await rollbackQuestionPresentedFailure(rollbackState);
		}
	}

	async function handleSelectOption(optionId: number) {
		if (!controllerSessionId || !currentQuestion || introNarrationPending) return;
		const questionAtAnswer = currentQuestion;
		autoContinueFailed = false;

		const response = await api.postLectureVideoInteraction(fetch, classId, threadId, {
			type: 'answer_submitted',
			controller_session_id: controllerSessionId,
			expected_state_version: stateVersion,
			idempotency_key: crypto.randomUUID(),
			question_id: currentQuestion.id,
			option_id: optionId
		});
		const expanded = api.expandResponse(response);
		if (failClosedOnConflict(expanded)) {
			return;
		}
		if (!expanded.error) {
			const continuationAtAnswer = expanded.data.lecture_video_session.current_continuation;
			appendAnswerToHistory(
				questionAtAnswer,
				optionId,
				continuationAtAnswer?.correct_option_id ?? null,
				continuationAtAnswer?.post_answer_text ?? null
			);
			applySession(expanded.data.lecture_video_session);

			// Record answer immediately so the marker updates
			if (continuationAtAnswer) {
				answeredQuestions.set(questionAtAnswer.id, {
					selectedOptionId: continuationAtAnswer.option_id,
					correctOptionId: continuationAtAnswer.correct_option_id,
					options: questionAtAnswer.options,
					postAnswerText: continuationAtAnswer.post_answer_text
				});
			}

			// Play post-answer narration if available
			if (continuationAtAnswer?.post_answer_narration_id) {
				postAnswerNarrationPending = true;
				void playNarration(
					continuationAtAnswer.post_answer_narration_id,
					() => {
						postAnswerNarrationPending = false;
						maybeAutoContinueAfterPostAnswer();
					},
					pausePostAnswerNarrationForChatSubmit
				);
			} else if (!hasVisiblePostAnswerFeedback(currentContinuation)) {
				maybeAutoContinueAfterPostAnswer();
			}

			// Clear subtitle
			subtitleText = null;
		}
	}

	async function requestContinue(): Promise<boolean> {
		if (autoContinueInFlight) {
			return false;
		}

		autoContinueInFlight = true;
		try {
			const didContinue = await handleContinue();
			autoContinueFailed = !didContinue;
			return didContinue;
		} finally {
			autoContinueInFlight = false;
		}
	}

	async function handleContinue(): Promise<boolean> {
		if (
			!controllerSessionId ||
			!currentContinuation ||
			!currentQuestion ||
			postAnswerNarrationPending
		) {
			return false;
		}

		// Save values before applySession clears them
		const resumeOffsetMs = currentContinuation.resume_offset_ms;
		const previousOffsetMs = currentTimeMs;
		const previousQuestionPlaybackLocked = questionPlaybackLocked;
		let optimisticPlayPromise: Promise<boolean> | null = null;
		const canSeekNow =
			videoElement != null && videoElement.readyState >= HTMLMediaElement.HAVE_METADATA;
		resumeOffsetOnCanPlay = canSeekNow ? null : resumeOffsetMs;
		if (videoElement) {
			questionPlaybackLocked = false;
			if (canSeekNow) {
				setVideoPosition(resumeOffsetMs);
			}
			optimisticPlayPromise = tryPlayVideo({
				suppressInteractionPost: true,
				queueRetryOnFailure: true
			});
		}

		// Ensure answered question is recorded (may already be set from handleSelectOption)
		if (!answeredQuestions.has(currentQuestion.id)) {
			answeredQuestions.set(currentQuestion.id, {
				selectedOptionId: currentContinuation.option_id,
				correctOptionId: currentContinuation.correct_option_id,
				options: currentQuestion.options,
				postAnswerText: currentContinuation.post_answer_text
			});
		}

		let expanded;
		let optimisticPlayStarted = false;
		try {
			const response = await api.postLectureVideoInteraction(fetch, classId, threadId, {
				type: 'video_resumed',
				controller_session_id: controllerSessionId,
				expected_state_version: stateVersion,
				idempotency_key: crypto.randomUUID(),
				offset_ms: resumeOffsetMs
			});
			expanded = api.expandResponse(response);
			optimisticPlayStarted = optimisticPlayPromise ? await optimisticPlayPromise : false;
		} catch {
			clearPendingVideoRetry();
			resumeOffsetOnCanPlay = null;
			questionPlaybackLocked = previousQuestionPlaybackLocked;
			if (videoElement) {
				if (!videoElement.paused) {
					suppressPauseInteraction = true;
					videoElement.pause();
				}
				setVideoPosition(previousOffsetMs);
			}
			return false;
		}

		if (failClosedOnConflict(expanded)) {
			resumeOffsetOnCanPlay = null;
			return false;
		}
		if (!expanded.error) {
			applySession(expanded.data.lecture_video_session);
			questionPresentedForId = null;
			subtitleText = null;

			// Resume video at the continue offset
			if (videoElement && !optimisticPlayStarted) {
				const canSeekNow = videoElement.readyState >= HTMLMediaElement.HAVE_METADATA;
				resumeOffsetOnCanPlay = canSeekNow ? null : resumeOffsetMs;
				if (canSeekNow) {
					setVideoPosition(resumeOffsetMs);
				}
				void tryPlayVideo({
					suppressInteractionPost: true,
					queueRetryOnFailure: true
				});
			}
			return true;
		}

		clearPendingVideoRetry();
		resumeOffsetOnCanPlay = null;
		questionPlaybackLocked = previousQuestionPlaybackLocked;
		if (videoElement) {
			if (!videoElement.paused) {
				suppressPauseInteraction = true;
				videoElement.pause();
			}
			setVideoPosition(previousOffsetMs);
		}
		return false;
	}

	function handleQuestionClick(markerId: number) {
		scrollToQuestionId = markerId;
	}

	async function handleManualPlaybackRequest() {
		if (manualPlaybackTarget === 'narration' && currentNarrationAudio) {
			try {
				await currentNarrationAudio.play();
				clearPendingVideoRetry();
			} catch {
				queueNarrationRetry();
			}
			return;
		}

		const reacquireControlPromise = controllerSessionId ? null : ensureControllerSession();
		if (reacquireControlPromise && !(await reacquireControlPromise)) {
			return;
		}

		await tryPlayVideo({
			suppressInteractionPost: true,
			queueRetryOnFailure: true
		});
	}

	// =========================================================================
	// Page unload
	// =========================================================================

	function handleBeforeUnload() {
		void cleanupLectureVideoSession({ postPause: true, releaseControl: true });
	}
</script>

{#if !historyLoaded && !initError}
	<div class="h-full w-full bg-white"></div>
{:else if initError}
	<div class="flex h-full w-full items-center justify-center p-4">
		<div
			class="flex w-full max-w-2xl flex-col gap-4 rounded-2xl border border-orange/30 bg-orange-light px-6 py-5 text-slate-900 shadow-sm sm:flex-row sm:items-center sm:justify-between"
		>
			<div class="flex flex-col gap-1">
				<div class="text-base font-semibold text-slate-900">Let's get you back on track</div>
				<div class="text-sm text-slate-700">{initError.detail}</div>
			</div>
			{#if initErrorCanRefresh}
				<button
					type="button"
					class="inline-flex shrink-0 items-center justify-center rounded-full bg-orange px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-orange-dark focus:ring-2 focus:ring-orange focus:ring-offset-2 focus:outline-none"
					onclick={refreshLesson}
				>
					Refresh lesson
				</button>
			{/if}
		</div>
	</div>
{:else}
	<div class="h-full w-full overflow-hidden">
		<div
			class="mx-auto flex h-full w-full max-w-screen-2xl flex-col gap-6 px-4 py-4 lg:px-6 xl:grid xl:grid-cols-5 xl:items-stretch xl:justify-center xl:gap-8 xl:py-6"
		>
			<div
				class="col-span-3 flex max-h-[40%] min-h-0 min-w-0 shrink-0 flex-col gap-4 xl:h-full xl:max-h-none xl:shrink"
			>
				{#if !canParticipate}
					<div
						class="shrink-0 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700"
					>
						You can view this lecture thread, but playback control and question responses are
						available only to participants.
					</div>
				{/if}
				{#if isCompleted && isDesktopLayout}
					<LectureVideoCompletedView
						{classId}
						{threadId}
						initialInteractions={historyInteractions}
					/>
				{:else if !isCompleted}
					<div
						class="mx-auto min-h-0 w-full max-w-[calc((40dvh-4rem)*16/9)] shrink-0 overflow-hidden rounded-3xl border border-slate-200 bg-white p-3 shadow-xl xl:max-h-[50%] xl:w-fit xl:max-w-none"
					>
						<LectureVideoPlayer
							src={lectureVideoSrc}
							displayTitle={sessionState === 'awaiting_answer'
								? 'Answer the comprehension check to continue'
								: title}
							startOffsetMs={initialStartOffsetMs}
							{questionMarkers}
							{subtitleText}
							disabled={!canParticipate || playbackLocked}
							{activeQuestionIds}
							{furthestOffsetMs}
							manualPlaybackPrompt={playbackRequiresManualStart}
							bind:videoElement
							bind:currentTimeMs
							bind:paused
							bind:effectiveVolume={playerVolume}
							ontimeupdate={handleTimeUpdate}
							onseek={handleSeek}
							onended={handleVideoEnded}
							oncanplay={handleCanPlay}
							onerror={() =>
								failClosedControl(
									'We could not load this video lesson. Refresh the lesson and try again.'
								)}
							onplay={handlePlay}
							onpause={handlePause}
							onquestionclick={handleQuestionClick}
							onmanualplayrequest={handleManualPlaybackRequest}
						/>
					</div>
					{#if isDesktopLayout}
						<div class="min-h-0 flex-1">
							<LectureVideoQuestionGallery
								{allQuestions}
								currentQuestionId={currentQuestion?.id ?? null}
								currentQuestion={visibleCurrentQuestion}
								{currentContinuation}
								{sessionState}
								{answeredQuestions}
								answeringDisabled={!canParticipate || introNarrationPending}
								{scrollToQuestionId}
								onselectOption={handleSelectOption}
								{...continuePromptProps}
								onscrollcomplete={clearQuestionScrollTarget}
							/>
						</div>
					{/if}
				{/if}
			</div>
			{#if isDesktopLayout}
				<div class="col-span-2 h-full min-h-0 min-w-0">
					{@render chat?.()}
				</div>
			{:else}
				<div class="flex min-h-0 flex-1 flex-col gap-4">
					{#if hasMobileChecksPanel && hasMobileChatPanel}
						<div class="shrink-0 rounded-2xl border border-slate-200 bg-slate-50 p-1">
							<div class="grid grid-cols-2 gap-1" role="tablist" aria-label="Lecture panels">
								<button
									type="button"
									role="tab"
									class={mobileSegmentClass('checks')}
									aria-selected={activeMobilePanel === 'checks'}
									onclick={() => (activeMobilePanel = 'checks')}
								>
									Comprehension Checks
								</button>
								<button
									type="button"
									role="tab"
									class={mobileSegmentClass('chat')}
									aria-selected={activeMobilePanel === 'chat'}
									onclick={() => (activeMobilePanel = 'chat')}
								>
									Chat
								</button>
							</div>
						</div>
					{/if}
					{#if hasMobileChecksPanel && (!hasMobileChatPanel || activeMobilePanel === 'checks')}
						<div class="min-h-0 flex-1 overflow-y-auto">
							{#if isCompleted}
								<LectureVideoCompletedView
									{classId}
									{threadId}
									initialInteractions={historyInteractions}
								/>
							{:else}
								<LectureVideoQuestionGallery
									{allQuestions}
									currentQuestionId={currentQuestion?.id ?? null}
									currentQuestion={visibleCurrentQuestion}
									{currentContinuation}
									{sessionState}
									{answeredQuestions}
									answeringDisabled={!canParticipate || introNarrationPending}
									{scrollToQuestionId}
									onselectOption={handleSelectOption}
									{...continuePromptProps}
									onscrollcomplete={clearQuestionScrollTarget}
								/>
							{/if}
						</div>
					{/if}
					{#if hasMobileChatPanel && (!hasMobileChecksPanel || activeMobilePanel === 'chat')}
						<div class="min-h-0 flex-1">
							{@render chat?.()}
						</div>
					{/if}
				</div>
			{/if}
		</div>
	</div>
{/if}
