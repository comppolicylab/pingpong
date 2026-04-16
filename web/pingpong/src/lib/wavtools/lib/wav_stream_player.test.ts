import { afterEach, describe, expect, it, vi } from 'vitest';

import { WavStreamPlayer } from './wav_stream_player';

describe('WavStreamPlayer', () => {
	afterEach(() => {
		vi.useRealTimers();
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
});
