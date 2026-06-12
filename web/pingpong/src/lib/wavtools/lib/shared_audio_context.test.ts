import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { FakeAudioContext, stubWebAudioGlobals } from './fake_audio_context_test_util';

// The module keeps per-sample-rate contexts in module state, so each test
// imports a fresh copy.
const loadModule = async () => await import('./shared_audio_context');

describe('shared_audio_context', () => {
	beforeEach(() => {
		vi.resetModules();
	});

	afterEach(() => {
		vi.unstubAllGlobals();
		vi.restoreAllMocks();
	});

	it('returns null when Web Audio is unavailable', async () => {
		const { unlockSharedAudioContext, getSharedAudioContext } = await loadModule();

		expect(unlockSharedAudioContext(24000)).toBeNull();
		expect(getSharedAudioContext(24000)).toBeNull();
	});

	it('creates one context per sample rate, resumes it, and reuses it', async () => {
		const instances = stubWebAudioGlobals();
		const { unlockSharedAudioContext } = await loadModule();

		const first = unlockSharedAudioContext(24000) as unknown as FakeAudioContext;
		const second = unlockSharedAudioContext(24000) as unknown as FakeAudioContext;

		expect(first).not.toBeNull();
		expect(second).toBe(first);
		expect(instances).toHaveLength(1);
		expect(first.sampleRate).toBe(24000);
		// Resumed while suspended, and only once: the second unlock sees the
		// context already running.
		expect(first.resume).toHaveBeenCalledTimes(1);
		// The worklet module loads at most once per context.
		expect(first.audioWorklet.addModule).toHaveBeenCalledTimes(1);
	});

	it('replaces a context once it has been closed', async () => {
		const instances = stubWebAudioGlobals();
		const { unlockSharedAudioContext } = await loadModule();

		const first = unlockSharedAudioContext(24000) as unknown as FakeAudioContext;
		await first.close();
		const second = unlockSharedAudioContext(24000) as unknown as FakeAudioContext;

		expect(second).not.toBe(first);
		expect(instances).toHaveLength(2);
	});

	it('retries the worklet module load after a failure', async () => {
		stubWebAudioGlobals();
		const { getSharedAudioContext, ensureStreamProcessorModule } = await loadModule();

		const context = getSharedAudioContext(24000)!;
		const addModule = (context as unknown as FakeAudioContext).audioWorklet.addModule;
		addModule.mockRejectedValueOnce(new Error('blocked'));

		await expect(ensureStreamProcessorModule(context)).rejects.toThrow('blocked');
		await expect(ensureStreamProcessorModule(context)).resolves.toBeUndefined();
		expect(addModule).toHaveBeenCalledTimes(2);
	});
});
