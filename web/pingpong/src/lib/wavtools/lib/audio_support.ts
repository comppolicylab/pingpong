export const AUDIO_WORKLET_UNSUPPORTED_MESSAGE =
	'Voice mode requires AudioWorklet support, which is unavailable in this browser or embedded context.';

export const isAudioWorkletSupported = (): boolean => {
	if (typeof window === 'undefined') {
		return false;
	}

	return (
		typeof AudioContext !== 'undefined' &&
		typeof AudioWorkletNode !== 'undefined' &&
		'audioWorklet' in AudioContext.prototype
	);
};
