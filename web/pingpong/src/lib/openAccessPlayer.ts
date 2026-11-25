import * as api from '$lib/api';
import {
	getOpenAccessSession,
	isFatalOpenAccessError,
	onOpenAccessError,
	setOpenAccessSession,
	type OpenAccessSession
} from '$lib/stores/openAccess';

const MESSAGE_PREFIX = 'pingpong:oa:';
const RENEW_BEFORE_EXPIRY_MS = 60_000;
const MIN_RENEW_DELAY_MS = 10_000;

type PlayerCallbacks = {
	onSession: (session: OpenAccessSession) => void;
	onError: (errorCode: string) => void;
};

const errorCode = (error: { error_code?: string | null }) =>
	error.error_code || 'open_access_unavailable';

export const takeLaunchCode = (hash: string) => new URLSearchParams(hash.slice(1)).get('code');

export const startOpenAccessPlayer = async (
	f: api.Fetcher,
	launchCode: string | null,
	{ onSession, onError }: PlayerCallbacks
) => {
	const config = api.expandResponse(await api.getOpenAccessConfig(f));
	if (config.error) {
		onError(errorCode(config.error));
		return () => undefined;
	}
	const parentOrigin = config.data.origin;
	let renewTimer: ReturnType<typeof setTimeout> | undefined;

	const post = (type: string, payload: Record<string, unknown> = {}) => {
		if (window.parent !== window) {
			window.parent.postMessage({ type: `${MESSAGE_PREFIX}${type}`, ...payload }, parentOrigin);
		}
	};

	let started = false;

	const fail = (code: string) => {
		post('error', { errorCode: code });
		if (!isFatalOpenAccessError(code)) return;
		clearTimeout(renewTimer);
		onError(code);
	};

	const start = (session: OpenAccessSession) => {
		started = true;
		onSession(session);
		post('ready', { sessionId: session.sessionId });
	};

	const scheduleRenewal = (session: OpenAccessSession) => {
		clearTimeout(renewTimer);
		renewTimer = setTimeout(
			() => post('renew', { sessionId: session.sessionId }),
			Math.max(session.expiresAt - Date.now() - RENEW_BEFORE_EXPIRY_MS, MIN_RENEW_DELAY_MS)
		);
	};

	const exchange = async (code: string) => {
		const response = api.expandResponse(await api.exchangeOpenAccessCode(f, code));
		if (response.error) {
			fail(errorCode(response.error));
			return null;
		}
		const session = {
			accessToken: response.data.access_token,
			expiresAt: Date.now() + response.data.expires_in * 1000,
			classId: response.data.class_id,
			threadId: response.data.thread_id,
			sessionId: response.data.session_id
		};
		setOpenAccessSession(session);
		scheduleRenewal(session);
		return session;
	};

	const onMessage = async (event: MessageEvent) => {
		if (event.origin !== parentOrigin || event.source !== window.parent) return;
		if (event.data?.type === `${MESSAGE_PREFIX}code` && typeof event.data.code === 'string') {
			const session = await exchange(event.data.code);
			if (session && !started) start(session);
		}
	};

	window.addEventListener('message', onMessage);
	onOpenAccessError(fail);

	const stored = getOpenAccessSession();
	if (launchCode) {
		const session = await exchange(launchCode);
		if (session) start(session);
	} else if (stored && stored.expiresAt > Date.now()) {
		scheduleRenewal(stored);
		start(stored);
	} else if (stored && window.parent !== window) {
		post('renew', { sessionId: stored.sessionId });
	} else {
		fail('open_access_code_missing');
	}

	return () => {
		clearTimeout(renewTimer);
		window.removeEventListener('message', onMessage);
		onOpenAccessError(null);
	};
};
