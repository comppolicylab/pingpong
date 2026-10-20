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
	const node = { connect: vi.fn().mockReturnThis() };
	vi.stubGlobal('window', globalThis);
	vi.stubGlobal(
		'AudioContext',
		class extends FakeAudioContext {
			createMediaStreamSource = vi.fn(() => node);
		}
	);
	vi.stubGlobal(
		'AudioWorkletNode',
		class {
			port = {};
		}
	);
}

describe('microphone access and selection', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		vi.restoreAllMocks();
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

	it('keeps the access stream paused and reuses it when Start selects the same microphone', async () => {
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
