const SESSION_KEY = 'pingpong.session';

type LtiStorageTarget = string | null;

const isNonEmptyString = (v: unknown): v is string => typeof v === 'string' && v.length > 0;

const getCookie = (name: string): string | null => {
  if (typeof document === 'undefined') return null;
  const m = document.cookie.match(new RegExp(`(?:^|; )${name.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&')}=([^;]*)`));
  return m ? decodeURIComponent(m[1]) : null;
};

const getSessionStorageString = (key: string): string | null => {
  try {
    const v = sessionStorage.getItem(key);
    return isNonEmptyString(v) ? v : null;
  } catch {
    return null;
  }
};

const setSessionStorageString = (key: string, value: string | null) => {
  try {
    if (value === null) sessionStorage.removeItem(key);
    else sessionStorage.setItem(key, value);
  } catch {
    // ignore
  }
};

const resolveTargetWindow = (storageTarget: string | null): Window | null => {
  if (!window.parent || window.parent === window) return null;
  if (storageTarget && storageTarget !== '_parent') {
    try {
      const frame = window.parent.frames?.namedItem(storageTarget);
      if (frame) return frame as unknown as Window;
    } catch {
      // ignore
    }
  }
  return window.parent;
};

const sendWithTimeout = <T extends Record<string, unknown>>(
  targetWindow: Window,
  msg: Record<string, unknown>,
  origin: string,
  timeoutMs: number
): Promise<T | null> => {
  return new Promise((resolve) => {
    let done = false;
    const cleanup = () => {
      if (done) return;
      done = true;
      window.removeEventListener('message', onMessage);
      clearTimeout(timer);
    };

    const onMessage = (event: MessageEvent) => {
      const data = event.data;
      if (!data || typeof data !== 'object') return;
      const record = data as Record<string, unknown>;
      if (record.message_id !== msg.message_id) return;
      if (record.key !== msg.key) return;
      cleanup();
      resolve(record as T);
    };

    const timer = setTimeout(() => {
      cleanup();
      resolve(null);
    }, timeoutMs);

    window.addEventListener('message', onMessage);
    try {
      targetWindow.postMessage(msg, origin);
    } catch {
      cleanup();
      resolve(null);
    }
  });
};

const uuid = () => {
  try {
    if (crypto && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  } catch {
    // ignore
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
};

export const initPingPongSessionFromLtiStorage = async (): Promise<string | null> => {
  // Cookie already set (or at least readable); nothing to do.
  if (getCookie('session')) return null;

  // If we already have it in our own sessionStorage, use that.
  const existing = getSessionStorageString('pingpong.session_token');
  if (existing) return existing;

  const storageTarget: LtiStorageTarget =
    getSessionStorageString('pingpong.lti_storage_target') ?? null;
  const platformOrigin: string | null =
    getSessionStorageString('pingpong.lti_platform_origin') ?? null;

  const targetWindow =
    resolveTargetWindow(storageTarget) ??
    // Heuristic fallback (RCE launches sometimes lack sibling frames).
    (window.parent && window.parent !== window ? window.parent : null);

  if (!targetWindow) return null;

  const message = {
    subject: 'lti.get_data',
    key: SESSION_KEY,
    message_id: uuid()
  };

  const timeoutMs = 800;

  // Spec path: send to platform origin, and to the configured forwarding frame/parent.
  if (platformOrigin) {
    const res = await sendWithTimeout<{ value?: unknown }>(
      targetWindow,
      message,
      platformOrigin,
      timeoutMs
    );
    if (res && (res.value === null || isNonEmptyString(res.value))) {
      const token = res.value === null ? null : (res.value as string);
      if (token) setSessionStorageString('pingpong.session_token', token);
      return token;
    }
  }

  // Backwards-compatible / non-spec fallback: wildcard origin.
  const wildcardRes = await sendWithTimeout<{ value?: unknown }>(
    targetWindow,
    message,
    '*',
    timeoutMs
  );
  if (wildcardRes && (wildcardRes.value === null || isNonEmptyString(wildcardRes.value))) {
    const token = wildcardRes.value === null ? null : (wildcardRes.value as string);
    if (token) setSessionStorageString('pingpong.session_token', token);
    return token;
  }

  // Final fallback: if we were targeting a sibling frame, try the parent directly.
  if (window.parent && window.parent !== window && targetWindow !== window.parent) {
    const parentRes = await sendWithTimeout<{ value?: unknown }>(
      window.parent,
      message,
      '*',
      timeoutMs
    );
    if (parentRes && (parentRes.value === null || isNonEmptyString(parentRes.value))) {
      const token = parentRes.value === null ? null : (parentRes.value as string);
      if (token) setSessionStorageString('pingpong.session_token', token);
      return token;
    }
  }

  return null;
};

export const clearPingPongSessionInLtiStorage = async (): Promise<void> => {
  const storageTarget: LtiStorageTarget =
    getSessionStorageString('pingpong.lti_storage_target') ?? null;
  const platformOrigin: string | null =
    getSessionStorageString('pingpong.lti_platform_origin') ?? null;

  const targetWindow = resolveTargetWindow(storageTarget);
  if (!targetWindow) return;

  const message = {
    subject: 'lti.put_data',
    key: SESSION_KEY,
    value: null,
    message_id: uuid()
  };

  const timeoutMs = 800;
  if (platformOrigin) {
    await sendWithTimeout(targetWindow, message, platformOrigin, timeoutMs);
  }
  await sendWithTimeout(targetWindow, message, '*', timeoutMs);
};
