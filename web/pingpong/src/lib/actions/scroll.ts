import type { Message } from '$lib/stores/thread';

export type ScrollParams = {
	messages: Message[];
	threadId: number;
	streaming: boolean;
};

export const scroll = (el: HTMLDivElement, params: ScrollParams) => {
	const scrollEl = el;
	let lastScrollTop = scrollEl.scrollTop;
	let userPausedAutoScroll = false;
	let isProgrammaticScroll = false;
	let settleFrame: number | null = null;
	let settlePassesRemaining = 0;
	let lastKnownScrollHeight = scrollEl.scrollHeight;
	let lastMessageId: string | null = params.messages[params.messages.length - 1]?.data.id ?? null;
	let currentThreadId = params.threadId;
	let isStreaming = params.streaming;

	const scrollToBottom = () => {
		isProgrammaticScroll = true;
		scrollEl.scrollTo({
			top: scrollEl.scrollHeight,
			behavior: 'smooth'
		});
		requestAnimationFrame(() => {
			lastScrollTop = scrollEl.scrollTop;
			lastKnownScrollHeight = scrollEl.scrollHeight;
			isProgrammaticScroll = false;
		});
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

			const scrollHeightChanged = scrollEl.scrollHeight !== lastKnownScrollHeight;
			scrollToBottom();
			lastKnownScrollHeight = scrollEl.scrollHeight;
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
			lastScrollTop = scrollEl.scrollTop;
			return;
		}
		const isScrollingUp = scrollEl.scrollTop < lastScrollTop - 5;

		if (isScrollingUp) {
			userPausedAutoScroll = true;
		}
		if (isStreaming) {
			const isScrollingDown = scrollEl.scrollTop > lastScrollTop;
			const distanceFromBottom = scrollEl.scrollHeight - scrollEl.scrollTop - scrollEl.clientHeight;
			if (userPausedAutoScroll && isScrollingDown && distanceFromBottom < 50) {
				userPausedAutoScroll = false;
			}
		}
		lastScrollTop = scrollEl.scrollTop;
	};

	const mutationObserver = new MutationObserver(() => {
		if (isStreaming) scheduleScrollToBottom(4);
	});
	const onDescendantLoad = () => {
		if (isStreaming) scheduleScrollToBottom(4);
	};

	scrollEl.addEventListener('scroll', onScroll, { passive: true });
	scrollEl.addEventListener('load', onDescendantLoad, true);
	mutationObserver.observe(scrollEl, {
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
				lastKnownScrollHeight = scrollEl.scrollHeight;
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
			mutationObserver.disconnect();
			scrollEl.removeEventListener('load', onDescendantLoad, true);
			scrollEl.removeEventListener('scroll', onScroll);
		}
	};
};
