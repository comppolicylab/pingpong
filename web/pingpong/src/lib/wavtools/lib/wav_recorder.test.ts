import { afterEach, describe, expect, it, vi } from 'vitest';
import { WavRecorder } from './wav_recorder';
import { FakeAudioContext } from './fake_audio_context_test_util';

function microphone(deviceId: string) {
	const track = {
		readyState: 'live',
		getSettings: () => ({ deviceId }),
		stop: vi.fn(() => {
			track.readyState = 'ended';
		})
	};
	return {
		track,
		stream: { getTracks: () => [track], getAudioTracks: () => [track] } as unknown as MediaStream
	};
}
function environment() {
	let listener: () => Promise<void>;
	const devices = [
		{ kind: 'audioinput', deviceId: 'usb', groupId: 'usb', label: 'USB microphone' }
	] as MediaDeviceInfo[];
	const media = {
		getUserMedia: vi.fn(),
		enumerateDevices: vi.fn().mockResolvedValue(devices),
		addEventListener: vi.fn((_: string, cb: () => Promise<void>) => {
			listener = cb;
		}),
		removeEventListener: vi.fn()
	};
	const query = vi.fn().mockRejectedValue(new TypeError('unsupported permission query'));
	vi.stubGlobal('navigator', { mediaDevices: media, permissions: { query } });
	return { media, query, devices, notify: () => listener() };
}
function audio() {
	const node = { connect: vi.fn().mockReturnThis(), disconnect: vi.fn() };
	const contexts: FakeAudioContext[] = [];
	const processors: {
		port: { postMessage: ReturnType<typeof vi.fn>; onmessage: ((e: MessageEvent) => void) | null };
		disconnect: ReturnType<typeof vi.fn>;
	}[] = [];
	vi.stubGlobal('window', globalThis);
	vi.stubGlobal(
		'AudioContext',
		class extends FakeAudioContext {
			constructor(options?: { sampleRate?: number }) {
				super(options);
				contexts.push(this);
			}
			createMediaStreamSource = vi.fn(() => node);
		}
	);
	vi.stubGlobal(
		'AudioWorkletNode',
		class {
			disconnect = vi.fn();
			port = {
				onmessage: null as ((e: MessageEvent) => void) | null,
				postMessage: vi.fn(({ event, id }: { event: string; id: number }) => {
					this.port.onmessage?.({
						data: {
							event: 'receipt',
							id,
							data:
								event === 'export'
									? {
											audio: {
												bitsPerSample: 16,
												channels: [new Float32Array(1)],
												data: new Int16Array(1)
											}
										}
									: {}
						}
					} as MessageEvent);
				})
			};
			constructor() {
				processors.push(this);
			}
		}
	);
	return { contexts, processors };
}

describe('microphone access and selection', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		vi.restoreAllMocks();
	});

	it('lists microphones while access is live, then releases every temporary track before Start', async () => {
		const env = environment();
		const mic = microphone('built-in');
		env.media.getUserMedia.mockResolvedValue(mic.stream);
		env.media.enumerateDevices.mockImplementationOnce(async () => {
			expect(mic.track.stop).not.toHaveBeenCalled();
			return env.devices;
		});
		const recorder = new WavRecorder();
		expect(await recorder.requestMicrophoneAccess()).toEqual(env.devices);
		expect(mic.track.stop).toHaveBeenCalledOnce();
		expect(recorder.stream).toBeNull();
		expect(recorder.processor).toBeNull();
		expect(recorder.recording).toBe(false);
		const selected = microphone('usb');
		env.media.getUserMedia.mockResolvedValueOnce(selected.stream);
		audio();
		await recorder.begin('usb');
		expect(env.media.getUserMedia).toHaveBeenLastCalledWith({
			audio: { deviceId: { exact: 'usb' } }
		});
		expect(recorder.stream).toBe(selected.stream);
		await recorder.quit();
	});

	it('releases temporary access when device enumeration fails', async () => {
		const env = environment();
		const mic = microphone('usb');
		env.media.getUserMedia.mockResolvedValue(mic.stream);
		env.media.enumerateDevices.mockRejectedValueOnce(new Error('enumeration failed'));
		const recorder = new WavRecorder();
		await expect(recorder.requestMicrophoneAccess()).rejects.toThrow('enumeration failed');
		expect(mic.track.stop).toHaveBeenCalledOnce();
		expect(recorder.stream).toBeNull();
	});

	it('cannot leave a late permission stream active after navigation cleanup', async () => {
		const env = environment();
		const mic = microphone('usb');
		let grant!: (stream: MediaStream) => void;
		env.media.getUserMedia.mockReturnValueOnce(
			new Promise<MediaStream>((resolve) => {
				grant = resolve;
			})
		);
		const recorder = new WavRecorder();
		const permission = recorder.requestMicrophoneAccess();
		await recorder.quit();
		grant(mic.stream);
		await permission;
		expect(mic.track.stop).toHaveBeenCalledOnce();
		expect(recorder.stream).toBeNull();
	});

	it('enumerates and refreshes named microphones without acquiring or querying permission', async () => {
		const env = environment();
		const recorder = new WavRecorder();
		expect(await recorder.listDevices()).toEqual(env.devices);
		const changed = vi.fn();
		recorder.listenForDeviceChange(changed);
		expect(env.media.enumerateDevices).toHaveBeenCalledTimes(1);
		await env.notify();
		expect(changed).toHaveBeenCalledWith(env.devices);
		expect(env.media.getUserMedia).not.toHaveBeenCalled();
		expect(env.query).not.toHaveBeenCalled();
	});

	it('reports an empty first device change after the only microphone is removed', async () => {
		const env = environment();
		const recorder = new WavRecorder();
		await recorder.listDevices();
		const changed = vi.fn();
		recorder.listenForDeviceChange(changed);
		env.media.enumerateDevices.mockResolvedValue([]);
		await env.notify();
		expect(changed).toHaveBeenCalledExactlyOnceWith([]);
		await env.notify();
		expect(changed).toHaveBeenCalledTimes(1);
		expect(env.media.getUserMedia).not.toHaveBeenCalled();
	});

	it('can stop capture for a setup retry while preserving device updates', async () => {
		const env = environment();
		const mic = microphone('usb');
		env.media.getUserMedia.mockResolvedValue(mic.stream);
		const recorder = new WavRecorder();
		const changed = vi.fn();
		recorder.listenForDeviceChange(changed);
		await recorder.prepareMicrophone();
		await recorder.quit({ keepDeviceListener: true });
		expect(mic.track.stop).toHaveBeenCalledTimes(1);
		expect(recorder.stream).toBeNull();
		expect(env.media.removeEventListener).not.toHaveBeenCalled();
		await env.notify();
		expect(changed).toHaveBeenCalledExactlyOnceWith(env.devices);
		expect(env.media.getUserMedia).toHaveBeenCalledTimes(1);
		await recorder.quit();
		expect(env.media.removeEventListener).toHaveBeenCalledTimes(1);
	});

	it('reuses an existing live capture stream when the selected microphone matches', async () => {
		const env = environment();
		audio();
		const mic = microphone('usb');
		env.media.getUserMedia.mockResolvedValue(mic.stream);
		const recorder = new WavRecorder();
		await recorder.prepareMicrophone();
		expect(recorder.processor).toBeNull();
		expect(recorder.recording).toBe(false);
		expect(mic.track.stop).not.toHaveBeenCalled();
		await recorder.listDevices();
		await recorder.begin('usb');
		expect(env.media.getUserMedia).toHaveBeenCalledExactlyOnceWith({ audio: true });
		expect(recorder.stream).toBe(mic.stream);
		expect(recorder.recording).toBe(false);
	});

	it('starts the selected microphone directly when device names were already available', async () => {
		const env = environment();
		audio();
		const mic = microphone('usb');
		env.media.getUserMedia.mockResolvedValue(mic.stream);
		const recorder = new WavRecorder();
		await recorder.listDevices();
		await recorder.begin('usb');
		expect(env.media.getUserMedia).toHaveBeenCalledExactlyOnceWith({
			audio: { deviceId: { exact: 'usb' } }
		});
	});

	it.each(['NotAllowedError', 'NotFoundError', 'NotReadableError', 'SecurityError'])(
		'preserves %s from microphone acquisition at Start',
		async (name) => {
			const env = environment();
			audio();
			const error = new DOMException('Microphone unavailable', name);
			env.media.getUserMedia.mockRejectedValueOnce(error);
			await expect(new WavRecorder().begin('usb')).rejects.toBe(error);
		}
	);

	it('acquires the chosen replacement before stopping the permission stream', async () => {
		const env = environment();
		const initial = microphone('built-in'),
			chosen = microphone('usb');
		env.media.getUserMedia
			.mockResolvedValueOnce(initial.stream)
			.mockImplementationOnce(async () => {
				expect(initial.track.stop).not.toHaveBeenCalled();
				return chosen.stream;
			});
		const recorder = new WavRecorder();
		await recorder.prepareMicrophone();
		await recorder.prepareMicrophone('usb');
		expect(initial.track.stop).toHaveBeenCalledTimes(1);
		expect(chosen.track.stop).not.toHaveBeenCalled();
		expect(recorder.stream).toBe(chosen.stream);
		expect(env.media.getUserMedia).toHaveBeenLastCalledWith({
			audio: { deviceId: { exact: 'usb' } }
		});
	});

	it('keeps the old stream if switching fails and releases it on cleanup', async () => {
		const env = environment(),
			initial = microphone('built-in');
		env.media.getUserMedia
			.mockResolvedValueOnce(initial.stream)
			.mockRejectedValueOnce(new Error('device missing'));
		const recorder = new WavRecorder();
		await recorder.prepareMicrophone();
		await expect(recorder.prepareMicrophone('usb')).rejects.toThrow('device missing');
		expect(initial.track.stop).not.toHaveBeenCalled();
		expect(recorder.stream).toBe(initial.stream);
		await recorder.quit();
		expect(initial.track.stop).toHaveBeenCalledTimes(1);
		expect(recorder.stream).toBeNull();
	});

	it('reacquires an ended microphone instead of relying on a stale grant', async () => {
		const env = environment(),
			initial = microphone('usb'),
			replacement = microphone('usb');
		env.media.getUserMedia
			.mockResolvedValueOnce(initial.stream)
			.mockResolvedValueOnce(replacement.stream);
		const recorder = new WavRecorder();
		await recorder.prepareMicrophone();
		initial.track.readyState = 'ended';
		await recorder.prepareMicrophone('usb');
		expect(env.media.getUserMedia).toHaveBeenCalledTimes(2);
		expect(recorder.stream).toBe(replacement.stream);
	});

	it.each(['removed', 'replaced'])(
		'ignores a refresh after its listener was %s',
		async (action) => {
			const env = environment();
			let finish!: (devices: MediaDeviceInfo[]) => void;
			env.media.enumerateDevices.mockReturnValueOnce(
				new Promise<MediaDeviceInfo[]>((resolve) => {
					finish = resolve;
				})
			);
			const recorder = new WavRecorder(),
				stale = vi.fn();
			recorder.listenForDeviceChange(stale);
			const refreshing = env.notify();
			recorder.listenForDeviceChange(action === 'removed' ? null : vi.fn());
			finish(env.devices);
			await refreshing;
			expect(stale).not.toHaveBeenCalled();
		}
	);

	it('handles a failed device refresh without requesting permission', async () => {
		const env = environment();
		vi.spyOn(console, 'warn').mockImplementation(() => {});
		env.media.enumerateDevices.mockRejectedValueOnce(new Error('device list unavailable'));
		const recorder = new WavRecorder();
		recorder.listenForDeviceChange(vi.fn());
		await expect(env.notify()).resolves.toBeUndefined();
		expect(env.media.getUserMedia).not.toHaveBeenCalled();
	});

	it('refreshes labels even when the microphone IDs have not changed', async () => {
		const env = environment();
		const recorder = new WavRecorder(),
			changed = vi.fn();
		recorder.listenForDeviceChange(changed);
		env.media.enumerateDevices.mockResolvedValueOnce([{ ...env.devices[0], label: '' }]);
		await env.notify();
		await env.notify();
		expect(changed).toHaveBeenCalledTimes(2);
		expect(changed).toHaveBeenLastCalledWith(env.devices);
		expect(env.media.getUserMedia).not.toHaveBeenCalled();
	});
});

describe('streaming capture cleanup', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		vi.restoreAllMocks();
	});

	it('streams chunks but discards the unsent tail and skips WAV export on quit', async () => {
		const env = environment();
		const mic = microphone('usb');
		env.media.getUserMedia.mockResolvedValue(mic.stream);
		const { contexts, processors } = audio();
		const createUrl = vi.spyOn(URL, 'createObjectURL');
		const recorder = new WavRecorder({ streamingOnly: true });
		await recorder.begin('usb');
		const onChunk = vi.fn();
		await recorder.record(onChunk, 8);
		const processor = processors[0];
		expect(processor.port.postMessage).toHaveBeenCalledWith({
			event: 'start',
			id: expect.any(Number),
			data: { streamingOnly: true }
		});
		for (const size of [8, 2]) {
			processor.port.onmessage?.({
				data: { event: 'chunk', data: { raw: new ArrayBuffer(size), mono: new ArrayBuffer(size) } }
			} as MessageEvent);
		}
		expect(onChunk).toHaveBeenCalledOnce();
		const ending = recorder.quit();
		expect(mic.track.stop).toHaveBeenCalledOnce();
		await ending;
		await recorder.quit();
		expect(onChunk).toHaveBeenCalledOnce();
		expect(processor.port.postMessage.mock.calls.map(([data]) => data.event)).toEqual([
			'start',
			'stop'
		]);
		expect(createUrl).not.toHaveBeenCalled();
		expect(processor.disconnect).toHaveBeenCalledOnce();
		expect(processor.port.onmessage).toBeNull();
		expect(contexts[0].close).toHaveBeenCalledOnce();
		expect(recorder.stream).toBeNull();
		expect(recorder.processor).toBeNull();
	});

	it('still exports WAV data for callers using the default recording mode', async () => {
		const env = environment();
		const mic = microphone('usb');
		env.media.getUserMedia.mockResolvedValue(mic.stream);
		const { contexts, processors } = audio();
		const recorder = new WavRecorder();
		await recorder.begin('usb');
		const result = await recorder.end();
		expect(result?.blob).toBeInstanceOf(Blob);
		expect(processors[0].port.postMessage.mock.calls.map(([data]) => data.event)).toEqual([
			'stop',
			'export'
		]);
		expect(contexts[0].close).toHaveBeenCalledOnce();
		if (result) URL.revokeObjectURL(result.url);
	});

	it('releases the microphone and audio context even when stopping the worklet fails', async () => {
		const env = environment();
		const mic = microphone('usb');
		env.media.getUserMedia.mockResolvedValue(mic.stream);
		const { contexts, processors } = audio();
		const recorder = new WavRecorder({ streamingOnly: true });
		await recorder.begin('usb');
		processors[0].port.postMessage.mockImplementationOnce(() => {
			throw new Error('worklet gone');
		});
		await expect(recorder.quit()).rejects.toThrow('worklet gone');
		expect(mic.track.stop).toHaveBeenCalledOnce();
		expect(processors[0].disconnect).toHaveBeenCalledOnce();
		expect(contexts[0].close).toHaveBeenCalledOnce();
		expect(recorder.processor).toBeNull();
		await recorder.quit();
	});
});
