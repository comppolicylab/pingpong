import { vi } from 'vitest';

/**
 * Test-only stand-in for AudioContext, shaped to satisfy
 * isAudioWorkletSupported() (audioWorklet must live on the prototype) and the
 * calls WavStreamPlayer.connect()/close() make.
 */
export class FakeAudioContext {
	state: AudioContextState = 'suspended';
	sampleRate: number;
	destination = {};
	resume = vi.fn(() => {
		this.state = 'running';
		return Promise.resolve();
	});
	close = vi.fn(() => {
		this.state = 'closed';
		return Promise.resolve();
	});
	createAnalyser = vi.fn(() => ({
		fftSize: 0,
		smoothingTimeConstant: 0,
		connect: vi.fn(),
		disconnect: vi.fn()
	}));
	createGain = vi.fn(() => ({
		gain: { value: 1 },
		connect: vi.fn(),
		disconnect: vi.fn()
	}));
	#audioWorklet = {
		addModule: vi.fn(() => Promise.resolve())
	};

	constructor(options?: { sampleRate?: number }) {
		this.sampleRate = options?.sampleRate ?? 44100;
	}

	// Class getter so 'audioWorklet' in AudioContext.prototype is true.
	get audioWorklet() {
		return this.#audioWorklet;
	}
}

/**
 * Install window/AudioContext/AudioWorkletNode globals so the wavtools audio
 * support check passes. Returns the list of contexts constructed. Callers
 * must run vi.unstubAllGlobals() afterwards.
 */
export function stubWebAudioGlobals(): FakeAudioContext[] {
	const instances: FakeAudioContext[] = [];
	class TrackingAudioContext extends FakeAudioContext {
		constructor(options?: { sampleRate?: number }) {
			super(options);
			instances.push(this);
		}
	}
	vi.stubGlobal('window', globalThis);
	vi.stubGlobal('AudioContext', TrackingAudioContext);
	vi.stubGlobal('AudioWorkletNode', class {});
	return instances;
}
