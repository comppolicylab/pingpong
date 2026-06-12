import { StreamProcessorSrc } from './worklets/stream_processor';
import { isAudioWorkletSupported } from './audio_support';

// Long-lived contexts are intentional. TTS currently uses one sample rate, but
// closed entries are pruned below so future rates do not accumulate stale refs.
const contextsBySampleRate = new Map<number, AudioContext>();
const workletLoads = new WeakMap<AudioContext, Promise<void>>();

/**
 * Get (or lazily create) the long-lived shared AudioContext for a sample rate.
 *
 * PCM written to the stream processor worklet plays at the context's rate, so
 * callers must request the rate their audio is encoded at.
 *
 * Returns null when Web Audio / AudioWorklet is unavailable or creation fails.
 */
export function getSharedAudioContext(sampleRate: number): AudioContext | null {
	if (!isAudioWorkletSupported()) {
		return null;
	}
	let context = contextsBySampleRate.get(sampleRate) ?? null;
	if (context && context.state === 'closed') {
		contextsBySampleRate.delete(sampleRate);
		context = null;
	}
	if (!context) {
		try {
			context = new AudioContext({ sampleRate });
		} catch (err) {
			console.warn('Shared AudioContext creation failed', err);
			return null;
		}
		contextsBySampleRate.set(sampleRate, context);
	}
	return context;
}

/**
 * Ensure the stream processor worklet module is loaded on a context, loading
 * it at most once per context.
 */
export function ensureStreamProcessorModule(context: AudioContext): Promise<void> {
	let load = workletLoads.get(context);
	if (!load) {
		load = context.audioWorklet.addModule(StreamProcessorSrc);
		workletLoads.set(context, load);
		load.catch(() => {
			// Drop the cached rejection so the next call can retry.
			if (workletLoads.get(context) === load) {
				workletLoads.delete(context);
			}
		});
	}
	return load;
}

/**
 * Synchronously create/resume the shared AudioContext and start loading its
 * worklet module.
 *
 * MUST be called from within a user-gesture call stack. Safari only allows an
 * AudioContext to start when it is created or resumed synchronously inside a
 * gesture handler; a resume() issued later (e.g. when a network chunk arrives)
 * can stay pending forever under autoplay policies, as can one issued from an
 * embedded context such as an LTI iframe without autoplay delegation.
 */
export function unlockSharedAudioContext(sampleRate: number): AudioContext | null {
	const context = getSharedAudioContext(sampleRate);
	if (!context) {
		return null;
	}
	if (context.state === 'suspended') {
		context.resume().catch((err) => {
			console.warn('Shared AudioContext resume failed', err);
		});
	}
	void ensureStreamProcessorModule(context).catch(() => {
		// Logged by the player when it tries to connect; unlock is best-effort.
	});
	return context;
}
