import { afterEach, describe, expect, it, vi } from 'vitest';

import { WavStreamPlayer } from './wav_stream_player';
import { FakeAudioContext, stubWebAudioGlobals } from './fake_audio_context_test_util';

describe('WavStreamPlayer', () => {
	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
		vi.restoreAllMocks();
	});

	it('returns null when closed before an interrupt response arrives', async () => {
		const player = new WavStreamPlayer();
		const disconnect = vi.fn();
		const postMessage = vi.fn();
		const close = vi.fn().mockResolvedValue(undefined);

		(
			player as unknown as {
				stream: { disconnect: () => void; port: { postMessage: (message: object) => void } };
				context: { close: () => Promise<void> };
			}
		).stream = {
			disconnect,
			port: { postMessage }
		};
		(player as unknown as { context: { close: () => Promise<void> } }).context = { close };

		const pendingOffset = player.interrupt();
		await player.close();

		await expect(pendingOffset).resolves.toBeNull();
		expect(postMessage).toHaveBeenCalledTimes(1);
		expect(disconnect).toHaveBeenCalledTimes(1);
		expect(close).toHaveBeenCalledTimes(1);
	});

	it('returns null when no offset response arrives before the timeout', async () => {
		vi.useFakeTimers();
		const player = new WavStreamPlayer();
		const postMessage = vi.fn();

		(
			player as unknown as {
				stream: { port: { postMessage: (message: object) => void } };
			}
		).stream = {
			port: { postMessage }
		};

		const pendingOffset = player.getTrackSampleOffset();
		await vi.advanceTimersByTimeAsync(300);

		await expect(pendingOffset).resolves.toBeNull();
		expect(postMessage).toHaveBeenCalledTimes(1);
	});

	it('can signal that no more streaming audio will be added', () => {
		const player = new WavStreamPlayer();
		const postMessage = vi.fn();

		(
			player as unknown as {
				stream: { port: { postMessage: (message: object) => void } };
			}
		).stream = {
			port: { postMessage }
		};

		player.finish();

		expect(postMessage).toHaveBeenCalledWith({ event: 'finish' });
	});

	it('reports an empty reply once and rejects its late audio', () => {
		const onPlaybackSettled = vi.fn();
		const player = new WavStreamPlayer({ onPlaybackSettled });
		player.finishTrack('empty');
		player.finishTrack('empty');
		expect(onPlaybackSettled).toHaveBeenCalledExactlyOnceWith({
			trackId: 'empty',
			outcome: 'discarded',
			played: false
		});
		expect(player.add16BitPCM(new Int16Array(128), 'empty', 'late')).toBeUndefined();
	});

	it('fences all old-stream replies while a replacement plays and ignores the old stop', async () => {
		stubWebAudioGlobals();
		const nodes: {
			port: { postMessage: ReturnType<typeof vi.fn>; onmessage: (event: { data: object }) => void };
			disconnect: ReturnType<typeof vi.fn>;
		}[] = [];
		vi.stubGlobal(
			'AudioWorkletNode',
			class {
				port = { postMessage: vi.fn(), onmessage: vi.fn() };
				connect = vi.fn();
				disconnect = vi.fn();
				constructor() {
					nodes.push(this);
				}
			}
		);
		const onPlaybackSettled = vi.fn();
		const onPlaybackStopped = vi.fn();
		const player = new WavStreamPlayer({
			stopOnEmptyBuffer: false,
			onPlaybackSettled,
			onPlaybackStopped
		});
		await player.connect();
		player.add16BitPCM(new Int16Array(256), 'playing', 'part-1');
		player.add16BitPCM(new Int16Array(128), 'queued', 'part-2');
		player.finishTrack('playing');
		expect(nodes[0].port.postMessage).toHaveBeenCalledWith({
			event: 'finish_track',
			trackId: 'playing'
		});
		const interrupted = player.interrupt();
		let secondFinished = false;
		const secondInterrupt = player.interrupt().then((offset) => {
			secondFinished = true;
			return offset;
		});
		await Promise.resolve();
		expect(secondFinished).toBe(false);
		player.add16BitPCM(new Int16Array(128), 'next', 'part-3');
		expect(nodes).toHaveLength(2);
		expect(player.add16BitPCM(new Int16Array(128), 'queued', 'late')).toBeUndefined();
		for (const data of [
			{ event: 'track_settled', trackId: 'playing', outcome: 'interrupted', played: true },
			{ event: 'track_settled', trackId: 'queued', outcome: 'discarded', played: false }
		])
			nodes[0].port.onmessage({ data });
		const command = nodes[0].port.postMessage.mock.calls.find(
			([data]) => data.event === 'interrupt'
		)?.[0];
		nodes[0].port.onmessage({
			data: { event: 'offset', requestId: command.requestId, trackId: 'playing', offset: 128 }
		});
		nodes[0].port.onmessage({ data: { event: 'stop' } });
		await expect(interrupted).resolves.toMatchObject({ trackId: 'playing', offset: 128 });
		await expect(secondInterrupt).resolves.toBeNull();
		expect(
			nodes[0].port.postMessage.mock.calls.filter(([data]) => data.event === 'interrupt')
		).toHaveLength(1);
		expect(onPlaybackSettled.mock.calls.map(([data]) => data.trackId)).toEqual([
			'playing',
			'queued'
		]);
		expect(onPlaybackStopped).not.toHaveBeenCalled();
		expect(player.add16BitPCM(new Int16Array(128), 'next', 'part-4')).toBeDefined();
		nodes[0].port.onmessage({
			data: { event: 'track_settled', trackId: 'queued', outcome: 'discarded', played: false }
		});
		expect(onPlaybackSettled).toHaveBeenCalledTimes(2);
		await player.close();
	});

	it('stops playback when finish is called before a stream starts', () => {
		const onPlaybackStopped = vi.fn();
		const player = new WavStreamPlayer({ onPlaybackStopped });

		player.finish();

		expect(onPlaybackStopped).toHaveBeenCalledTimes(1);
	});

	it('reuses a provided context with a matching sample rate and never closes it', async () => {
		const instances = stubWebAudioGlobals();
		const shared = new FakeAudioContext({ sampleRate: 24000 });
		const player = new WavStreamPlayer({
			sampleRate: 24000,
			context: shared as unknown as AudioContext
		});

		await player.connect();

		// No context of its own was created.
		expect(instances).toHaveLength(0);
		expect(shared.resume).toHaveBeenCalledTimes(1);
		expect(shared.audioWorklet.addModule).toHaveBeenCalledTimes(1);

		await player.close();
		expect(shared.close).not.toHaveBeenCalled();
	});

	it('creates and closes its own context when the provided sample rate differs', async () => {
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
		const instances = stubWebAudioGlobals();
		const mismatched = new FakeAudioContext({ sampleRate: 48000 });
		const player = new WavStreamPlayer({
			sampleRate: 24000,
			context: mismatched as unknown as AudioContext
		});

		await player.connect();

		expect(instances).toHaveLength(1);
		expect(instances[0].sampleRate).toBe(24000);
		expect(mismatched.resume).not.toHaveBeenCalled();
		expect(warn).toHaveBeenCalledWith(
			'Provided AudioContext sample rate 48000 does not match 24000; creating a dedicated context.'
		);

		await player.close();
		expect(instances[0].close).toHaveBeenCalledTimes(1);
		expect(mismatched.close).not.toHaveBeenCalled();
	});
});
