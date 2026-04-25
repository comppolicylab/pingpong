<script module lang="ts">
	export type LectureVideoViewHandle = {
		pauseForChatSubmit: () => Promise<void>;
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
		LectureVideoContinuation,
		LectureVideoInteractionHistoryItem
	} from '$lib/api';
	import { hasVisiblePostAnswerFeedback } from '$lib/lectureVideoFeedback';
	import { mergeQuestionOptions } from '$lib/utils/lecture-video';
	import LectureVideoPlayer from './LectureVideoPlayer.svelte';
	import LectureVideoQuestionSidebar from './LectureVideoQuestionSidebar.svelte';
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

	let {
		classId,
		threadId,
		lectureVideoSrc,
		title = 'Lecture Video',
		canParticipate = true,
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
		initialSession?: LectureVideoSession | null;
		chatAvailable?: boolean;
		playerVolume?: number;
		chat?: Snippet;
	} = $props();
	const dispatch = createEventDispatcher<{
		sessionchange: LectureVideoSession;
		playbackresumed: void;
	}>();

	// --- Session state ---
	let controllerSessionId: string | null = $state(null);
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

	// --- Player state ---
	let videoElement: HTMLVideoElement | null = $state(null);
	let currentTimeMs: number = $state(0);
	let paused: boolean = $state(true);
	let subtitleText: string | null = $state(null);
	let playerDisabled: boolean = $state(false);
	let questionPlaybackLocked: boolean = $state(false);
	let furthestOffsetMs: number = $state(0);
	let initialStartOffsetMs: number = $state(0);
	let initialAutoplayAttempted: boolean = $state(false);
	let videoReadyForPlayback: boolean = $state(false);
	let introNarrationPending: boolean = $state(false);
	let postAnswerNarrationPending: boolean = $state(false);

	// --- UI state ---
	let scrollToQuestionId: number | null = $state(null);
	let isDesktopLayout: boolean = $state(false);
	let activeMobilePanel: 'checks' | 'chat' | null = $state('checks');
	let historyLoaded: boolean = $state(false);
	let historyInteractions: LectureVideoInteractionHistoryItem[] = $state([]);
	let initError: string | null = $state(null);
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

	// --- Lease renewal ---
	let leaseInterval: ReturnType<typeof setInterval> | null = null;
	const narrationAudioSrcById = new SvelteMap<number, Promise<string>>();
	const narrationObjectUrls = new SvelteSet<string>();
	const resolvedNarrationAudioSrcById = new SvelteMap<number, string>();
	let pendingNarrationCleanup: (() => void) | null = null;
	let currentNarrationAudio: HTMLAudioElement | null = null;
	let pendingVideoRetryCleanup: (() => void) | null = null;
	let manualPlaybackTarget: 'video' | 'narration' | null = $state(null);
	let autoContinueInFlight = $state(false);
	let autoContinueFailed = $state(false);
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
	let questionMarkers = $derived(
		[...allQuestions]
			.sort((a, b) => a.stopOffsetMs - b.stopOffsetMs)
			.map((q) => {
				const answer = answeredQuestions.get(q.id);
				const state: QuestionMarkerState =
					answer == null
						? 'upcoming'
						: answer.correctOptionId != null && answer.selectedOptionId === answer.correctOptionId
							? 'correct'
							: 'incorrect';
				return {
					id: q.id,
					offsetMs: q.stopOffsetMs,
					label: 'Comprehension Check',
					state
				};
			})
	);
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
		pendingNarrationCleanup?.();
		pendingNarrationCleanup = null;
		currentNarrationAudio?.pause();
		currentNarrationAudio = null;
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

		return () => {
			window.removeEventListener('beforeunload', handleBeforeUnload);
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
		return `rounded-xl px-4 py-2 text-sm font-medium transition-colors ${
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
		sessionState = 'playing';
		stateVersion = 1;
		currentQuestion = null;
		currentContinuation = null;
		answeredQuestions.clear();
		allQuestions = [];
		currentTimeMs = 0;
		paused = true;
		subtitleText = null;
		playerDisabled = false;
		questionPlaybackLocked = false;
		furthestOffsetMs = 0;
		initialStartOffsetMs = 0;
		initialAutoplayAttempted = false;
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
		revokeNarrationResources();
		clearPendingVideoRetry();
		autoContinueInFlight = false;
		autoContinueFailed = false;
	}

	function revokeNarrationResources() {
		for (const objectUrl of narrationObjectUrls) {
			URL.revokeObjectURL(objectUrl);
		}
		narrationObjectUrls.clear();
		narrationAudioSrcById.clear();
		resolvedNarrationAudioSrcById.clear();
		stopNarrationPlayback();
	}

	function clearPendingVideoRetry() {
		pendingVideoRetryCleanup?.();
		pendingVideoRetryCleanup = null;
		manualPlaybackTarget = null;
	}

	function maybeAutoContinueAfterPostAnswer() {
		void requestContinue();
	}

	function queueVideoRetry() {
		manualPlaybackTarget = 'video';
	}

	function queueNarrationRetry() {
		manualPlaybackTarget = 'narration';
	}

	function failClosedControl(detail?: string | null) {
		if (leaseInterval) {
			clearInterval(leaseInterval);
			leaseInterval = null;
		}

		clearPendingVideoRetry();
		resumeOffsetOnCanPlay = null;
		stopNarrationPlayback();
		autoContinueInFlight = false;

		if (videoElement && !videoElement.paused) {
			suppressPauseInteraction = true;
			videoElement.pause();
		}

		controllerSessionId = null;
		playerDisabled = true;
		initError = detail || 'Lecture video control was lost. Please refresh to continue.';
	}

	function failClosedOnConflict(
		reason: string,
		expanded: { $status: number; error: { detail?: string } | null }
	): boolean {
		if (expanded.$status !== 409) {
			return false;
		}

		failClosedControl(expanded.error?.detail);
		return true;
	}

	async function postPlaybackInteraction(type: 'video_paused' | 'video_resumed') {
		const interactionControllerSessionId = controllerSessionId;
		if (!interactionControllerSessionId || sessionState !== 'playing') {
			return;
		}

		const expectedStateVersion = stateVersion;
		const offsetMs = Math.round(currentTimeMs);

		try {
			const response = await api.postLectureVideoInteraction(fetch, classId, threadId, {
				type,
				controller_session_id: interactionControllerSessionId,
				expected_state_version: expectedStateVersion,
				idempotency_key: crypto.randomUUID(),
				offset_ms: offsetMs
			});
			if (controllerSessionId !== interactionControllerSessionId) {
				return;
			}

			const expanded = api.expandResponse(response);
			if (failClosedOnConflict(`${type}-conflict`, expanded)) {
				return;
			}
			if (expanded.error) {
				failClosedControl(
					expanded.error.detail ||
						'Failed to sync lecture video playback. Please refresh to continue.'
				);
				return;
			}

			applySession(expanded.data.lecture_video_session);
		} catch (error) {
			if (controllerSessionId !== interactionControllerSessionId) {
				return;
			}
			failClosedControl(error instanceof Error ? error.message : String(error));
		}
	}

	async function tryPlayVideo(
		reason: string,
		{
			suppressInteractionPost = false,
			queueRetryOnFailure = false
		}: {
			suppressInteractionPost?: boolean;
			queueRetryOnFailure?: boolean;
		} = {}
	): Promise<boolean> {
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

	async function ensureControllerSession(): Promise<boolean> {
		if (controllerSessionId) {
			return true;
		}

		try {
			const response = await api.acquireLectureVideoControl(fetch, classId, threadId);
			const expanded = api.expandResponse(response);
			if (expanded.error) {
				failClosedControl(expanded.error.detail);
				return false;
			}

			controllerSessionId = expanded.data.controller_session_id;
			applySession(expanded.data.lecture_video_session);
			return true;
		} catch (error) {
			failClosedControl(error instanceof Error ? error.message : String(error));
			return false;
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

		stopNarrationPlayback();
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

		const response = await api.acquireLectureVideoControl(fetch, classId, threadId);
		const expanded = api.expandResponse(response);
		if (expanded.error) {
			failClosedControl(expanded.error.detail || 'Failed to start lecture session');
			return;
		}
		controllerSessionId = expanded.data.controller_session_id;

		applySession(expanded.data.lecture_video_session);

		// If resuming mid-session, seek video to last known offset
		const session = expanded.data.lecture_video_session;
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
				void playNarration(currentQuestion.intro_narration_id, {
					onEnded: () => {
						playerDisabled = false;
						introNarrationPending = false;
					},
					onError: () => {
						playerDisabled = false;
						introNarrationPending = false;
					}
				});
			}
		}

		if (
			sessionState === 'awaiting_post_answer_resume' &&
			currentContinuation?.post_answer_narration_id
		) {
			postAnswerNarrationPending = true;
			void playNarration(currentContinuation.post_answer_narration_id, {
				onEnded: () => {
					postAnswerNarrationPending = false;
					maybeAutoContinueAfterPostAnswer();
				},
				onError: () => {
					postAnswerNarrationPending = false;
					maybeAutoContinueAfterPostAnswer();
				}
			});
		} else if (
			sessionState === 'awaiting_post_answer_resume' &&
			!hasVisiblePostAnswerFeedback(currentContinuation)
		) {
			maybeAutoContinueAfterPostAnswer();
		}

		applyPendingResumeOffset();
		attemptInitialAutoplay();

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
					failClosedControl(expanded.error.detail);
					return;
				}
				if (controllerSessionId !== renewingControllerSessionId) {
					return;
				}
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
				initError = historyExpanded.error.detail || 'Failed to load lecture history';
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
			await tryPlayVideo('question-presented-rollback', {
				suppressInteractionPost: true,
				queueRetryOnFailure: true
			});
		}
	}

	function attemptInitialAutoplay() {
		if (
			initialAutoplayAttempted ||
			!videoReadyForPlayback ||
			!controllerSessionId ||
			!videoElement
		) {
			return;
		}
		if (sessionState !== 'playing' || playbackLocked) return;

		initialAutoplayAttempted = true;
		void tryPlayVideo('initial-autoplay', {
			suppressInteractionPost: true,
			queueRetryOnFailure: true
		});
	}

	function handleCanPlay() {
		applyPendingResumeOffset();
		videoReadyForPlayback = true;
		attemptInitialAutoplay();
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
		void postPlaybackInteraction('video_paused');
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
		void postPlaybackInteraction('video_resumed');
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
			if (failClosedOnConflict('video-seeked-conflict', expanded)) {
				return;
			}
			if (!expanded.error) {
				applySession(expanded.data.lecture_video_session);
				return;
			}

			setVideoPosition(fromOffsetMs);
			failClosedControl(
				expanded.error.detail ||
					'Failed to sync lecture video seek position. Please refresh to continue.'
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
			if (failClosedOnConflict('video-ended-conflict', expanded)) {
				return;
			}
			if (!expanded.error) {
				applySession(expanded.data.lecture_video_session);
				return;
			}

			failClosedControl(
				expanded.error.detail ||
					'Failed to complete lecture video session. Please refresh to continue.'
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
		handlers: {
			onEnded?: () => void;
			onError?: () => void;
		} = {}
	) {
		stopNarrationPlayback();

		try {
			const narrationSrc = await getNarrationAudioSrc(narrationId);
			const audio = new Audio(narrationSrc);
			audio.volume = playerVolume;
			currentNarrationAudio = audio;
			audio.addEventListener('ended', () => {
				if (manualPlaybackTarget === 'narration' && currentNarrationAudio === audio) {
					clearPendingVideoRetry();
				}
				if (currentNarrationAudio === audio) {
					currentNarrationAudio = null;
				}
				handlers.onEnded?.();
			});
			audio.addEventListener('error', () => {
				if (manualPlaybackTarget === 'narration' && currentNarrationAudio === audio) {
					clearPendingVideoRetry();
				}
				if (currentNarrationAudio === audio) {
					currentNarrationAudio = null;
				}
				handlers.onError?.();
			});
			try {
				await audio.play();
				clearPendingVideoRetry();
			} catch {
				pendingNarrationCleanup = () => {
					audio.pause();
					if (currentNarrationAudio === audio) {
						currentNarrationAudio = null;
					}
				};
				queueNarrationRetry();
			}
		} catch {
			currentNarrationAudio = null;
			handlers.onError?.();
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
			void playNarration(currentQuestion.intro_narration_id, {
				onEnded: () => {
					playerDisabled = false;
					introNarrationPending = false;
					void postQuestionPresented(rollbackState);
				},
				onError: () => {
					playerDisabled = false;
					introNarrationPending = false;
					void postQuestionPresented(rollbackState);
				}
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
			if (failClosedOnConflict('question-presented-conflict', expanded)) {
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
		if (failClosedOnConflict('answer-submitted-conflict', expanded)) {
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
				void playNarration(continuationAtAnswer.post_answer_narration_id, {
					onEnded: () => {
						postAnswerNarrationPending = false;
						maybeAutoContinueAfterPostAnswer();
					},
					onError: () => {
						postAnswerNarrationPending = false;
						maybeAutoContinueAfterPostAnswer();
					}
				});
			} else if (!hasVisiblePostAnswerFeedback(currentContinuation)) {
				maybeAutoContinueAfterPostAnswer();
			}

			// Clear subtitle
			subtitleText = null;
		}
	}

	async function requestContinue() {
		if (autoContinueInFlight) {
			return;
		}

		autoContinueInFlight = true;
		try {
			autoContinueFailed = !(await handleContinue());
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
			optimisticPlayPromise = tryPlayVideo('continue-click-optimistic', {
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

		if (failClosedOnConflict('continue-conflict', expanded)) {
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
				void tryPlayVideo('continue-post-response', {
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

		await tryPlayVideo('manual-play-button', {
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
			class="w-full max-w-2xl rounded-xl border border-amber-200 bg-amber-50 px-5 py-4 text-amber-900"
		>
			{initError}
		</div>
	</div>
{:else}
	<div class="h-full w-full overflow-hidden">
		<div
			class="mx-auto flex h-full w-full max-w-screen-2xl flex-col gap-6 px-4 py-4 lg:px-6 xl:grid xl:grid-cols-[minmax(0,1fr)_24rem] xl:items-stretch xl:gap-8 xl:py-6"
		>
			<div class="min-h-0 min-w-0 space-y-4 overflow-y-auto">
				{#if !canParticipate}
					<div
						class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700"
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
					<div class="overflow-hidden rounded-3xl border border-slate-200 bg-white p-3 shadow-xl">
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
									'The lecture video could not be loaded. Please refresh to try again.'
								)}
							onplay={handlePlay}
							onpause={handlePause}
							onquestionclick={handleQuestionClick}
							onmanualplayrequest={handleManualPlaybackRequest}
						/>
					</div>
				{/if}
			</div>
			{#if isDesktopLayout}
				<div class="flex min-h-0 min-w-0 flex-col gap-4 pt-3">
					{#if sessionState !== 'completed'}
						<LectureVideoQuestionSidebar
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
					<div class="min-h-0 flex-1">
						{@render chat?.()}
					</div>
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
									showHeading={!hasMobileChatPanel}
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
