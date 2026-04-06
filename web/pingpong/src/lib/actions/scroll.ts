import type { Message } from '$lib/stores/thread';

export type ScrollParams = {
	messages: Message[];
	threadId: number;
	streaming: boolean;
};

export const scroll = (el: HTMLDivElement, params: ScrollParams) => {
	const scrollEndSupported = 'onscrollend' in el;
	const programmaticScrollEpsilon = 2;
	const programmaticScrollTimeoutMs = 1500;
	let lastScrollTop = el.scrollTop;
	let userPausedAutoScroll = false;
	let isProgrammaticScroll = false;
	let targetScrollTop: number | null = null;
	let settleFrame: number | null = null;
	let settlePassesRemaining = 0;
	let programmaticScrollTimeout: ReturnType<typeof setTimeout> | null = null;
	let lastKnownScrollHeight = el.scrollHeight;
	let lastMessageId: string | null = params.messages[params.messages.length - 1]?.data.id ?? null;
	let currentThreadId = params.threadId;
	let isStreaming = params.streaming;

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

	const scrollToBottom = () => {
		clearProgrammaticScrollTimeout();
		isProgrammaticScroll = true;
		targetScrollTop = el.scrollHeight;
		el.scrollTo({
			top: targetScrollTop,
			behavior: 'smooth'
		});
		if (!scrollEndSupported && hasReachedProgrammaticTarget()) {
			completeProgrammaticScroll();
			return;
		}
		programmaticScrollTimeout = setTimeout(() => {
			completeProgrammaticScroll();
		}, programmaticScrollTimeoutMs);
	};

	const cancelSettledScroll = () => {
		if (settleFrame !== null) {
			cancelAnimationFrame(settleFrame);
			settleFrame = null;
		}
		settlePassesRemaining = 0;
	};

	const scheduleScrollToBottom = (passes = 6) => {
		if (userPausedAutoScroll) {
			return;
		}

		settlePassesRemaining = Math.max(settlePassesRemaining, passes);
		if (settleFrame !== null) {
			return;
		}

		const run = () => {
			settleFrame = null;
			if (userPausedAutoScroll) {
				settlePassesRemaining = 0;
				return;
			}

			const scrollHeightChanged = el.scrollHeight !== lastKnownScrollHeight;
			scrollToBottom();
			lastKnownScrollHeight = el.scrollHeight;
			settlePassesRemaining -= 1;
			if (scrollHeightChanged) {
				settlePassesRemaining = Math.max(settlePassesRemaining, 2);
			}
			if (settlePassesRemaining > 0) {
				settleFrame = requestAnimationFrame(run);
			}
		};

		settleFrame = requestAnimationFrame(run);
	};

	const onScroll = () => {
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

	const mutationObserver = new MutationObserver(() => {
		if (isStreaming) scheduleScrollToBottom(4);
	});
	const onDescendantLoad = () => {
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
				lastMessageId = null;
				lastScrollTop = 0;
				lastKnownScrollHeight = el.scrollHeight;
				scheduleScrollToBottom();
				return;
			}

			const nextMessages = nextParams.messages;
			const nextLastMessage = nextMessages[nextMessages.length - 1];
			const nextLastMessageId = nextLastMessage?.data.id ?? null;
			const hasNewTailMessage = nextLastMessageId && nextLastMessageId !== lastMessageId;
			const isCurrentUserTail =
				nextLastMessage?.data.role === 'user' &&
				nextLastMessage?.data.metadata?.is_current_user === true;
			lastMessageId = nextLastMessageId;

			if (isStreaming && !wasStreaming) {
				userPausedAutoScroll = false;
			}

			requestAnimationFrame(() => {
				if (hasNewTailMessage && isCurrentUserTail) {
					userPausedAutoScroll = false;
				}
				if (!userPausedAutoScroll && (hasNewTailMessage || isStreaming)) {
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
