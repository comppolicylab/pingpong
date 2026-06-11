import * as api from '$lib/api';

export function getMessageImageUrl({
	classId,
	threadId,
	messageId,
	fileId,
	imageProof
}: {
	classId: number;
	threadId: number;
	messageId: string;
	fileId: string;
	imageProof: string | null;
}) {
	if (imageProof) {
		return api.fullPath(
			`/class/${classId}/thread/${threadId}/message/${messageId}/image/${fileId}?proof=${imageProof}`
		);
	}
	return api.fullPath(`/class/${classId}/thread/${threadId}/message/${messageId}/image/${fileId}`);
}

export function getCodeInterpreterImageUrl({
	classId,
	threadId,
	version,
	message,
	item
}: {
	classId: number;
	threadId: number;
	version: number;
	message: api.OpenAIMessage;
	item: api.MessageContentCodeOutputImageFile;
}) {
	const fileId = item.image_file.file_id;
	const runId = item.run_id;
	const stepId = item.step_id;

	if (version <= 2 && runId && stepId) {
		return api.fullPath(
			`/class/${classId}/thread/${threadId}/run/${runId}/step/${stepId}/image/${fileId}`
		);
	}

	const ciCallId = item.ci_call_id ?? message.metadata?.['ci_call_id'];
	if (version <= 2 && typeof ciCallId === 'string' && ciCallId.length > 0) {
		return api.fullPath(`/class/${classId}/thread/${threadId}/ci_call/${ciCallId}/image/${fileId}`);
	}
	if (version <= 2) {
		return null;
	}
	return api.fullPath(`/class/${classId}/thread/${threadId}/image/${fileId}`);
}
