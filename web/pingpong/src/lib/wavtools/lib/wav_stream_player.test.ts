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

		await player.close();
		expect(instances[0].close).toHaveBeenCalledTimes(1);
		expect(mismatched.close).not.toHaveBeenCalled();
	});
});
