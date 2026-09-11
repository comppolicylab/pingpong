import { describe, expect, it, vi } from 'vitest';
import { createLessonInteractionQueue } from './lessonInteractionQueue';

type Interaction = {
	type: string;
	controller_session_id: string;
	expected_state_version: number;
	idempotency_key: string;
	to_offset_ms: number;
};

function deferred<T>() {
	let resolve!: (value: T) => void;
	let reject!: (reason: Error) => void;
	const promise = new Promise<T>((yes, no) => {
		resolve = yes;
		reject = no;
	});
	return { promise, resolve, reject };
}

function setup() {
	let controller: string | null = 'controller';
	let version = 1;
	const requests: ReturnType<typeof deferred<number | null>>[] = [];
	const send = vi.fn<(payload: Interaction) => Promise<number | null>>(() => {
		const request = deferred<number | null>();
		requests.push(request);
		return request.promise;
	});
	const enqueue = createLessonInteractionQueue({
		getControllerSessionId: () => controller,
		getStateVersion: () => version,
		setStateVersion: (next) => (version = next),
		getResponseVersion: (response: number | null) => response,
		send
	});
	return {
		enqueue,
		send,
		requests,
		getVersion: () => version,
		setController: (next: string | null) => (controller = next)
	};
}

function interaction(offset: number, type = 'video_seeked'): Interaction {
	return {
		type,
		controller_session_id: 'controller',
		expected_state_version: 1,
		idempotency_key: `${type}-${offset}`,
		to_offset_ms: offset
	};
}

describe('lesson interaction queue', () => {
	it('serializes rapid forward/backward seeks and playback events using acknowledged versions', async () => {
		const queue = setup();
		const payloads = [
			interaction(15000),
			interaction(30000),
			interaction(45000),
			interaction(30000),
			interaction(30000, 'video_paused')
		];
		const results = payloads.map(queue.enqueue);
		for (let i = 0; i < payloads.length; i++) {
			await vi.waitFor(() => expect(queue.send).toHaveBeenCalledTimes(i + 1));
			expect(queue.send).toHaveBeenNthCalledWith(i + 1, {
				...payloads[i],
				expected_state_version: i + 1
			});
			queue.requests[i].resolve(i + 2);
			await results[i];
		}
		expect(queue.getVersion()).toBe(6);
	});

	it.each(['response', 'network'])('drops pending actions after a %s failure', async (failure) => {
		const queue = setup();
		const first = queue.enqueue(interaction(15000));
		const second = queue.enqueue(interaction(30000));
		const results = Promise.allSettled([first, second]);
		await vi.waitFor(() => expect(queue.send).toHaveBeenCalledTimes(1));
		if (failure === 'response') queue.requests[0].resolve(null);
		else queue.requests[0].reject(new Error('Network failure'));
		expect((await results)[1].status).toBe('rejected');
		expect(queue.send).toHaveBeenCalledTimes(1);
		expect(queue.getVersion()).toBe(1);

		const next = queue.enqueue(interaction(45000));
		await vi.waitFor(() => expect(queue.send).toHaveBeenCalledTimes(2));
		queue.requests[1].resolve(2);
		await next;
		expect(queue.getVersion()).toBe(2);
	});

	it('discards queued actions and old response versions when the controller changes', async () => {
		const queue = setup();
		const first = queue.enqueue(interaction(15000));
		const second = queue.enqueue(interaction(30000));
		const results = Promise.allSettled([first, second]);
		await vi.waitFor(() => expect(queue.send).toHaveBeenCalledTimes(1));
		queue.setController('new-controller');
		queue.requests[0].resolve(2);
		expect((await results)[1].status).toBe('rejected');
		expect(queue.send).toHaveBeenCalledTimes(1);
		expect(queue.getVersion()).toBe(1);
	});
});
