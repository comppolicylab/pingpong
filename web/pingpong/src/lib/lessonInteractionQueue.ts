type VersionedInteraction = {
	controller_session_id: string;
	expected_state_version: number;
};

export function createLessonInteractionQueue<Payload extends VersionedInteraction, Response>({
	getControllerSessionId,
	getStateVersion,
	setStateVersion,
	getResponseVersion,
	send
}: {
	getControllerSessionId: () => string | null;
	getStateVersion: () => number;
	setStateVersion: (version: number) => void;
	getResponseVersion: (response: Response) => number | null;
	send: (payload: Payload) => Promise<Response>;
}): (payload: Payload) => Promise<Response> {
	let tail: Promise<void> = Promise.resolve();
	let generation = 0;

	return (payload) => {
		const queuedGeneration = generation;
		const result = tail.then(async () => {
			if (
				queuedGeneration !== generation ||
				payload.controller_session_id !== getControllerSessionId()
			) {
				throw new Error('Lesson control changed before the interaction could be saved.');
			}

			try {
				const response = await send({ ...payload, expected_state_version: getStateVersion() });
				const version = getResponseVersion(response);
				if (version === null) {
					// Pending actions rely on this mutation succeeding. Do not replay them after a failure.
					generation += 1;
				} else if (payload.controller_session_id === getControllerSessionId()) {
					setStateVersion(version);
				}
				return response;
			} catch (error) {
				generation += 1;
				throw error;
			}
		});
		tail = result.then(
			() => undefined,
			() => undefined
		);
		return result;
	};
}
