import type { Assistant, CopyAssistantRequest, Fetcher } from '$lib/api';
import * as api from '$lib/api';

export const defaultCopyName = (name: string) => {
	const suffix = ' (Copy)';
	const maxLen = 100;
	if (name.length + suffix.length > maxLen) {
		return `${name.slice(0, maxLen - suffix.length)}${suffix}`;
	}
	return `${name}${suffix}`;
};

export const parseTargetClassId = (value: string | number | null | undefined, fallback: number) => {
	const trimmed = value?.toString().trim();
	if (!trimmed) {
		return fallback;
	}
	const parsed = parseInt(trimmed, 10);
	if (Number.isNaN(parsed)) {
		return null;
	}
	return parsed;
};

export type CopyPermissionResult = {
	allowed: boolean;
	error: string;
};

export const checkCopyPermission = async (
	f: Fetcher,
	sourceClassId: number,
	assistantId: number,
	targetClassId: number
): Promise<CopyPermissionResult> => {
	try {
		const result = await api.copyAssistantCheck(f, sourceClassId, assistantId, {
			target_class_id: targetClassId
		});
		const expanded = api.expandResponse(result);
		if (expanded.error) {
			return {
				allowed: false,
				error: expanded.error.detail || 'Permission check failed.'
			};
		}
		return { allowed: !!expanded.data?.allowed, error: '' };
	} catch (err) {
		console.error('Failed to check copy permission', err);
		return {
			allowed: false,
			error: 'Unable to verify permissions right now.'
		};
	}
};

export type ExpandedResult<T> = {
	$status: number;
	data: T | null;
	error: (Error & { detail?: string }) | null;
};

export const buildCopyPayload = (
	name: string,
	fallbackName: string,
	targetClassId?: string | number | null
): { payload?: CopyAssistantRequest; error?: string } => {
	const requestedName = name.trim() || defaultCopyName(fallbackName);
	const safeName = requestedName.slice(0, 100);
	const payload: CopyAssistantRequest = { name: safeName };
	const targetString = targetClassId?.toString().trim();
	if (targetString) {
		const parsed = parseInt(targetString, 10);
		if (Number.isNaN(parsed)) {
			return { error: 'Invalid target class ID' };
		}
		payload.target_class_id = parsed;
	}
	return { payload };
};

export const performCopyAssistant = async (
	f: Fetcher,
	sourceClassId: number,
	assistantId: number,
	opts: { name: string; fallbackName: string; targetClassId?: string | number | null }
): Promise<ExpandedResult<Assistant>> => {
	const built = buildCopyPayload(opts.name, opts.fallbackName, opts.targetClassId);
	if (built.error || !built.payload) {
		return {
			$status: 400,
			error: { detail: built.error || 'Invalid copy payload' } as Error & { detail?: string },
			data: null
		};
	}
	const result = await api.copyAssistant(f, sourceClassId, assistantId, built.payload);
	return api.expandResponse(result) as ExpandedResult<Assistant>;
};

export const performDeleteAssistant = async (
	f: Fetcher,
	classId: number,
	assistantId: number
): Promise<ExpandedResult<api.GenericStatus>> => {
	const result = await api.deleteAssistant(f, classId, assistantId);
	return api.expandResponse(result) as ExpandedResult<api.GenericStatus>;
};
