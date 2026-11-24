import * as api from '$lib/api';
import {
	getOpenAccessSession,
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

	const fail = (code: string) => {
		clearTimeout(renewTimer);
		post('error', { errorCode: code });
		onError(code);
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

	const onMessage = (event: MessageEvent) => {
		if (event.origin !== parentOrigin || event.source !== window.parent) return;
		if (event.data?.type === `${MESSAGE_PREFIX}code` && typeof event.data.code === 'string') {
			exchange(event.data.code);
		}
	};

	window.addEventListener('message', onMessage);
	onOpenAccessError(fail);

	const stored = getOpenAccessSession();
	const session = launchCode
		? await exchange(launchCode)
		: stored && stored.expiresAt > Date.now()
			? stored
			: null;
	if (session) {
		if (!launchCode) scheduleRenewal(session);
		onSession(session);
		post('ready', { sessionId: session.sessionId });
	} else if (!launchCode) {
		fail('open_access_code_missing');
	}

	return () => {
		clearTimeout(renewTimer);
		window.removeEventListener('message', onMessage);
		onOpenAccessError(null);
	};
};
