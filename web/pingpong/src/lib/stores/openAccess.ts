import { browser } from '$app/environment';

export const OPEN_ACCESS_PATH_PREFIX = '/oa/';
export const OPEN_ACCESS_MARKER_HEADER = 'X-PingPong-OA';
export const OPEN_ACCESS_TOKEN_HEADER = 'X-PingPong-OA-Token';

const STORAGE_KEY = 'pingpong_oa_session';

export type OpenAccessSession = {
	accessToken: string;
	expiresAt: number;
	classId: number;
	threadId: number;
	sessionId: string;
};

type ErrorListener = (errorCode: string) => void;

let errorListener: ErrorListener | null = null;

export const isOpenAccessPage = () =>
	browser && window.location.pathname.startsWith(OPEN_ACCESS_PATH_PREFIX);

export const getOpenAccessSession = (): OpenAccessSession | null => {
	if (!isOpenAccessPage()) return null;
	try {
		const raw = sessionStorage.getItem(STORAGE_KEY);
		return raw ? (JSON.parse(raw) as OpenAccessSession) : null;
	} catch {
		return null;
	}
};

export const getOpenAccessToken = () => getOpenAccessSession()?.accessToken ?? null;

export const setOpenAccessSession = (session: OpenAccessSession) => {
	sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session));
};

export const clearOpenAccessSession = () => {
	if (browser) sessionStorage.removeItem(STORAGE_KEY);
};

export const onOpenAccessError = (listener: ErrorListener | null) => {
	errorListener = listener;
};

export const reportOpenAccessResponse = (response: Response) => {
	if (response.ok || !errorListener) return;
	const listener = errorListener;
	response
		.clone()
		.json()
		.then((payload) => {
			const errorCode = payload?.detail?.error_code;
			if (typeof errorCode === 'string') listener(errorCode);
		})
		.catch(() => undefined);
};
