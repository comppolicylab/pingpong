import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { stopVoiceSession } from './voiceSessionStop';

class Socket extends EventTarget {
	static OPEN = 1;
	readyState = 1;
	send = vi.fn();
	message(data: unknown) {
		this.dispatchEvent(new MessageEvent('message', { data }));
	}
	get websocket() {
		return this as unknown as WebSocket;
	}
}

describe('voice session save confirmation', () => {
	beforeEach(() => {
		vi.stubGlobal('WebSocket', Socket);
		vi.useFakeTimers();
	});
	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
		vi.restoreAllMocks();
	});

	it('waits for the save acknowledgement and removes listeners before the server closes', async () => {
		const socket = new Socket();
		const remove = vi.spyOn(socket, 'removeEventListener');
		let settled = false;
		const stopped = stopVoiceSession(socket.websocket).then(() => {
			settled = true;
		});
		expect(socket.send).toHaveBeenCalledExactlyOnceWith(JSON.stringify({ type: 'session.stop' }));
		for (const data of ['bad json', null, JSON.stringify({ type: 'response.done' })])
			socket.message(data);
		await Promise.resolve();
		expect(settled).toBe(false);
		socket.message(JSON.stringify({ type: 'session.stopped', saved: true }));
		socket.dispatchEvent(new Event('close'));
		await stopped;
		expect(remove).toHaveBeenCalledTimes(3);
		expect(vi.getTimerCount()).toBe(0);
	});

	it('registers the acknowledgement listener before sending stop', async () => {
		const socket = new Socket();
		socket.send.mockImplementation(() =>
			socket.message(JSON.stringify({ type: 'session.stopped', saved: true }))
		);
		await expect(stopVoiceSession(socket.websocket)).resolves.toBeUndefined();
	});

	it('rejects an explicit failed save', async () => {
		const socket = new Socket();
		const stopped = stopVoiceSession(socket.websocket);
		const result = expect(stopped).rejects.toThrow('could not save');
		socket.message(JSON.stringify({ type: 'session.stopped', saved: false }));
		await result;
		expect(vi.getTimerCount()).toBe(0);
	});

	it.each(['close', 'error'])('does not treat a socket %s as a saved session', async (type) => {
		const socket = new Socket();
		const stopped = stopVoiceSession(socket.websocket);
		const result = expect(stopped).rejects.toThrow('before the save was confirmed');
		socket.dispatchEvent(new Event(type));
		await result;
		expect(vi.getTimerCount()).toBe(0);
	});

	it('bounds the wait and ignores a late acknowledgement', async () => {
		const socket = new Socket();
		const stopped = stopVoiceSession(socket.websocket, 100);
		const result = expect(stopped).rejects.toThrow('timed out');
		await vi.advanceTimersByTimeAsync(100);
		await result;
		socket.message(JSON.stringify({ type: 'session.stopped', saved: true }));
		expect(vi.getTimerCount()).toBe(0);
	});

	it.each(['closed', 'send'])('cleans up after a %s failure', async (type) => {
		const socket = new Socket();
		if (type === 'closed') socket.readyState = 3;
		else
			socket.send.mockImplementation(() => {
				throw new Error('synthetic send failure');
			});
		await expect(stopVoiceSession(socket.websocket)).rejects.toThrow();
		expect(vi.getTimerCount()).toBe(0);
	});
});
