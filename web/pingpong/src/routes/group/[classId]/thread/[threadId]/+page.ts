import * as api from '$lib/api';
import { error } from '@sveltejs/kit';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch, params, parent }) => {
	const classId = parseInt(params.classId, 10);
	const threadId = parseInt(params.threadId, 10);
	const parentData = await parent();

	const [threadData, threadGrants] = await Promise.all([
		api.getThread(fetch, classId, threadId),
		api.grants(fetch, {
			canDelete: { target_type: 'thread', target_id: threadId, relation: 'can_delete' },
			canPublish: { target_type: 'thread', target_id: threadId, relation: 'can_publish' },
			canManageThreads: {
				target_type: 'class',
				target_id: classId,
				relation: 'can_manage_threads'
			}
		})
	]);

	const expanded = api.expandResponse(threadData);
	if (expanded.error) {
		error(expanded.$status || 500, expanded.error.detail || 'Failed to load thread');
	}

	let threadModel = '';
	let threadTools = '';
	let threadInteractionMode: api.InteractionMode | null = null;
	let threadRecording: api.VoiceModeRecordingInfo | null = null;
	let threadDisplayUserInfo = false;
	let threadPreventsUserDeletion = false;
	let threadLectureVideoMismatch = false;
	let threadLectureSlideMismatch = false;
	let assistantGrants = { canViewAssistant: false };
	threadTools = expanded.data.tools_available || '';
	threadModel = expanded.data.model || '';
	threadInteractionMode = expanded.data.thread.interaction_mode || 'chat';
	threadRecording = expanded.data.recording || null;
	threadDisplayUserInfo = expanded.data.thread.display_user_info || false;
	threadPreventsUserDeletion =
		!parentData.class?.private &&
		threadDisplayUserInfo &&
		(expanded.data.thread.prevent_user_thread_deletion || false);
	threadLectureVideoMismatch =
		expanded.data.lecture_video_matches_assistant === false &&
		threadInteractionMode === 'lecture_video';
	threadLectureSlideMismatch =
		expanded.data.lecture_slide_matches_assistant === false &&
		threadInteractionMode === 'lecture_slides';
	if (expanded.data.thread.assistant_id) {
		assistantGrants = await api.grants(fetch, {
			canViewAssistant: {
				target_type: 'assistant',
				target_id: expanded.data.thread.assistant_id,
				relation: 'can_view'
			}
		});
	}

	return {
		threadData,
		threadModel,
		threadInteractionMode,
		availableTools: threadTools,
		canDeleteThread:
			threadGrants.canDelete && (!threadPreventsUserDeletion || threadGrants.canManageThreads),
		threadDeletionDisabledByModerators:
			threadPreventsUserDeletion && !threadGrants.canManageThreads,
		canPublishThread: threadGrants.canPublish,
		canViewAssistant: assistantGrants.canViewAssistant,
		threadRecording,
		threadDisplayUserInfo,
		threadLectureVideoMismatch,
		threadLectureSlideMismatch,
		statusComponents: parentData.statusComponents ?? {}
	};
};
