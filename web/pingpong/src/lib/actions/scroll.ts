import type { Message } from '$lib/stores/thread';

export type ScrollParams = {
	messages: Message[];
	threadId: number;
	streaming: boolean;
	tailContentKey?: string | null;
};

export const scroll = (el: HTMLDivElement, params: ScrollParams) => {
	const scrollEndSupported = 'onscrollend' in el;
	const programmaticScrollEpsilon = 2;
	const programmaticScrollTimeoutMs = 1500;
	const bottomSettleWindowMs = 2500;
	let lastScrollTop = el.scrollTop;
	let userPausedAutoScroll = false;
	let isProgrammaticScroll = false;
	let targetScrollTop: number | null = null;
	let settleFrame: number | null = null;
	let settlePassesRemaining = 0;
	let programmaticScrollTimeout: ReturnType<typeof setTimeout> | null = null;
	let lastKnownScrollHeight = el.scrollHeight;
	let lastMessageId: string | null = params.messages[params.messages.length - 1]?.data.id ?? null;
	let lastTailContentKey: string | null = params.tailContentKey ?? null;
	let currentThreadId = params.threadId;
	let isStreaming = params.streaming;
	let preserveBottomUntil = Date.now() + bottomSettleWindowMs;

	const clearProgrammaticScrollTimeout = () => {
		if (programmaticScrollTimeout !== null) {
			clearTimeout(programmaticScrollTimeout);
			programmaticScrollTimeout = null;
		}
	};

	const completeProgrammaticScroll = () => {
		clearProgrammaticScrollTimeout();
		isProgrammaticScroll = false;
		targetScrollTop = null;
		lastScrollTop = el.scrollTop;
		lastKnownScrollHeight = el.scrollHeight;
	};

	const hasReachedProgrammaticTarget = () => {
		if (targetScrollTop === null) {
			return true;
		}
		return Math.abs(el.scrollTop - targetScrollTop) <= programmaticScrollEpsilon;
	};

	const getBottomScrollTop = () => Math.max(0, el.scrollHeight - el.clientHeight);
	const wasNearKnownBottom = () => lastKnownScrollHeight - lastScrollTop - el.clientHeight < 80;
	const isSettlingAtBottom = () => Date.now() < preserveBottomUntil;
	const shouldPreserveBottomAnchor = () =>
		!userPausedAutoScroll && (isProgrammaticScroll || wasNearKnownBottom() || isSettlingAtBottom());

	const scrollToBottom = (behavior: ScrollBehavior = 'smooth') => {
		clearProgrammaticScrollTimeout();
		isProgrammaticScroll = true;
		targetScrollTop = getBottomScrollTop();
		el.scrollTo({
			top: targetScrollTop,
			behavior
		});
		if (!scrollEndSupported && hasReachedProgrammaticTarget()) {
			completeProgrammaticScroll();
			return;
		}
		programmaticScrollTimeout = setTimeout(() => {
			completeProgrammaticScroll();
		}, programmaticScrollTimeoutMs);
	};

	const reanchorAfterShrink = () => {
		const scrollHeightDecreased = el.scrollHeight < lastKnownScrollHeight;
		// Use the previous scroll metrics to preserve whether the user was anchored before a shrink.
		const wasNearBottom = wasNearKnownBottom();
		if (!isStreaming || !scrollHeightDecreased || !wasNearBottom) {
			return false;
		}

		userPausedAutoScroll = false;
		clearProgrammaticScrollTimeout();
		isProgrammaticScroll = false;
		targetScrollTop = null;
		el.scrollTop = getBottomScrollTop();
		lastScrollTop = el.scrollTop;
		lastKnownScrollHeight = el.scrollHeight;
		scheduleScrollToBottom(4, true);
		return true;
	};

	const cancelSettledScroll = () => {
		if (settleFrame !== null) {
			cancelAnimationFrame(settleFrame);
			settleFrame = null;
		}
		settlePassesRemaining = 0;
	};

	const scheduleScrollToBottom = (passes = 6, force = false) => {
		if (userPausedAutoScroll && !force) {
			return;
		}

		settlePassesRemaining = Math.max(settlePassesRemaining, passes);
		if (settleFrame !== null) {
			return;
		}

		const run = () => {
			settleFrame = null;
			if (reanchorAfterShrink()) {
				settlePassesRemaining -= 1;
				if (settlePassesRemaining > 0) {
					settleFrame = requestAnimationFrame(run);
				}
				return;
			}
			if (userPausedAutoScroll && !force) {
				settlePassesRemaining = 0;
				return;
			}

			const scrollHeightChanged = el.scrollHeight !== lastKnownScrollHeight;
			scrollToBottom(force ? 'auto' : 'smooth');
			lastKnownScrollHeight = el.scrollHeight;
			settlePassesRemaining -= 1;
			if (scrollHeightChanged) {
				preserveBottomUntil = Date.now() + bottomSettleWindowMs;
				settlePassesRemaining = Math.max(settlePassesRemaining, 2);
			}
			if (settlePassesRemaining > 0) {
				settleFrame = requestAnimationFrame(run);
			}
		};

		settleFrame = requestAnimationFrame(run);
	};

	const onScroll = () => {
		if (reanchorAfterShrink()) {
			return;
		}

		if (isProgrammaticScroll) {
			if (hasReachedProgrammaticTarget()) {
				completeProgrammaticScroll();
				return;
			}
			const isScrollingUp = el.scrollTop < lastScrollTop - 5;
			if (
				isScrollingUp &&
				targetScrollTop !== null &&
				el.scrollTop < targetScrollTop - programmaticScrollEpsilon
			) {
				userPausedAutoScroll = true;
				preserveBottomUntil = 0;
				clearProgrammaticScrollTimeout();
				isProgrammaticScroll = false;
				targetScrollTop = null;
				lastScrollTop = el.scrollTop;
				lastKnownScrollHeight = el.scrollHeight;
				cancelSettledScroll();
				return;
			}
			return;
		}
		const isScrollingUp = el.scrollTop < lastScrollTop - 5;

		if (isScrollingUp) {
			userPausedAutoScroll = true;
			preserveBottomUntil = 0;
		}
		if (isStreaming) {
			const isScrollingDown = el.scrollTop > lastScrollTop;
			const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
			if (userPausedAutoScroll && isScrollingDown && distanceFromBottom < 50) {
				userPausedAutoScroll = false;
			}
		}
		lastScrollTop = el.scrollTop;
	};

	const reanchorAfterGrowth = () => {
		const scrollHeightIncreased = el.scrollHeight > lastKnownScrollHeight;
		if (!scrollHeightIncreased || !shouldPreserveBottomAnchor()) {
			return false;
		}
		preserveBottomUntil = Date.now() + bottomSettleWindowMs;
		scheduleScrollToBottom(4, true);
		return true;
	};

	const mutationObserver = new MutationObserver(() => {
		if (reanchorAfterShrink()) {
			return;
		}
		if (reanchorAfterGrowth()) {
			return;
		}
		if (isStreaming) scheduleScrollToBottom(4);
	});
	const onDescendantLoad = () => {
		if (reanchorAfterGrowth()) {
			return;
		}
		if (isStreaming) scheduleScrollToBottom(4);
	};
	const onScrollEnd = () => {
		if (isProgrammaticScroll) {
			completeProgrammaticScroll();
		}
	};

	el.addEventListener('scroll', onScroll, { passive: true });
	if (scrollEndSupported) {
		el.addEventListener('scrollend', onScrollEnd);
	}
	el.addEventListener('load', onDescendantLoad, true);
	mutationObserver.observe(el, {
		childList: true,
		subtree: true,
		characterData: true
	});
	scheduleScrollToBottom();

	return {
		update: (nextParams: ScrollParams) => {
			const wasStreaming = isStreaming;
			isStreaming = nextParams.streaming;

			if (nextParams.threadId !== currentThreadId) {
				currentThreadId = nextParams.threadId;
				userPausedAutoScroll = false;
				preserveBottomUntil = Date.now() + bottomSettleWindowMs;
				lastMessageId = null;
				lastTailContentKey = nextParams.tailContentKey ?? null;
				lastScrollTop = 0;
				lastKnownScrollHeight = el.scrollHeight;
				scheduleScrollToBottom();
				return;
			}

			const nextMessages = nextParams.messages;
			const nextLastMessage = nextMessages[nextMessages.length - 1];
			const nextLastMessageId = nextLastMessage?.data.id ?? null;
			const hasNewTailMessage = nextLastMessageId && nextLastMessageId !== lastMessageId;
			const nextTailContentKey = nextParams.tailContentKey ?? null;
			const hasTailContentChange = nextTailContentKey !== lastTailContentKey;
			const isCurrentUserTail =
				nextLastMessage?.data.role === 'user' &&
				nextLastMessage?.data.metadata?.is_current_user === true;
			lastMessageId = nextLastMessageId;
			lastTailContentKey = nextTailContentKey;

			if (isStreaming && !wasStreaming) {
				userPausedAutoScroll = false;
				preserveBottomUntil = Date.now() + bottomSettleWindowMs;
			}

			requestAnimationFrame(() => {
				reanchorAfterShrink();
				if (hasNewTailMessage && isCurrentUserTail) {
					userPausedAutoScroll = false;
				}
				if (!userPausedAutoScroll && (hasNewTailMessage || hasTailContentChange || isStreaming)) {
					preserveBottomUntil = Date.now() + bottomSettleWindowMs;
					scheduleScrollToBottom();
				}
			});
		},
		destroy: () => {
			cancelSettledScroll();
			clearProgrammaticScrollTimeout();
			mutationObserver.disconnect();
			el.removeEventListener('load', onDescendantLoad, true);
			el.removeEventListener('scroll', onScroll);
			if (scrollEndSupported) {
				el.removeEventListener('scrollend', onScrollEnd);
			}
		}
	};
};
