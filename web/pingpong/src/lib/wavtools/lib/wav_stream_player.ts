/**
 * Parts of this code are derived from the following copyrighted
 * material, the use of which is hereby acknowledged.
 *
 * OpenAI (openai-realtime-console)
 *
 * MIT License
 *
 * Copyright (c) 2024 OpenAI
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */

import { StreamProcessorSrc } from './worklets/stream_processor';
import { AudioAnalysis, type AudioAnalysisOutputType } from './analysis/audio_analysis';
import { AUDIO_WORKLET_UNSUPPORTED_MESSAGE, isAudioWorkletSupported } from './audio_support';

export type OnAudioPartStartedProcessor = (data: {
	trackId: string;
	eventId: string;
	timestamp: number;
}) => void;
export type OnPlaybackStoppedProcessor = () => void;
interface WavStreamPlayerOptions {
	sampleRate?: number;
	onAudioPartStarted?: OnAudioPartStartedProcessor;
	onPlaybackStopped?: OnPlaybackStoppedProcessor;
}

interface TrackSampleOffset {
	trackId: string | null;
	offset: number;
	currentTime: number;
}

const TRACK_SAMPLE_OFFSET_TIMEOUT_MS = 250;

/**
 * Plays audio streams received in raw PCM16 chunks from the browser
 * @class
 */
export class WavStreamPlayer {
	private scriptSrc: string;
	private sampleRate: number;
	private context: AudioContext | null;
	private stream: AudioWorkletNode | null;
	private analyser: AnalyserNode | null;
	private gainNode: GainNode | null;
	private trackSampleOffsets: Record<string, TrackSampleOffset>;
	private interruptedTrackIds: Record<string, boolean>;
	private onAudioPartStarted: OnAudioPartStartedProcessor | null;
	private onPlaybackStopped: OnPlaybackStoppedProcessor | null;

	/**
	 * Creates a new WavStreamPlayer instance
	 * @param {{sampleRate?: number, onAudioPartStarted?: OnAudioPartStartedProcessor}} options
	 * @returns {WavStreamPlayer}
	 */
	constructor({
		sampleRate = 44100,
		onAudioPartStarted,
		onPlaybackStopped
	}: WavStreamPlayerOptions = {}) {
		this.scriptSrc = StreamProcessorSrc;
		this.sampleRate = sampleRate;
		this.context = null;
		this.stream = null;
		this.analyser = null;
		this.gainNode = null;
		this.trackSampleOffsets = {};
		this.interruptedTrackIds = {};
		this.onAudioPartStarted = onAudioPartStarted || null;
		this.onPlaybackStopped = onPlaybackStopped || null;
	}

	/**
	 * Connects the audio context and enables output to speakers
	 * @returns {Promise<true>}
	 */
	async connect(): Promise<true> {
		if (!isAudioWorkletSupported()) {
			throw new Error(AUDIO_WORKLET_UNSUPPORTED_MESSAGE);
		}

		this.context = new AudioContext({ sampleRate: this.sampleRate });
		if (this.context.state === 'suspended') {
			await this.context.resume();
		}
		try {
			await this.context.audioWorklet.addModule(this.scriptSrc);
		} catch (e) {
			throw new Error(`Could not add audioWorklet module: ${this.scriptSrc}`, { cause: e });
		}
		const analyser = this.context.createAnalyser();
		analyser.fftSize = 8192;
		analyser.smoothingTimeConstant = 0.1;
		this.analyser = analyser;
		const gainNode = this.context.createGain();
		gainNode.connect(this.context.destination);
		this.gainNode = gainNode;
		return true;
	}

	/**
	 * Gets the current frequency domain data from the playing track
	 * @param {"frequency"|"music"|"voice"} [analysisType]
	 * @param {number} [minDecibels] default -100
	 * @param {number} [maxDecibels] default -30
	 * @returns {AudioAnalysisOutputType}
	 */
	getFrequencies(
		analysisType: 'frequency' | 'music' | 'voice' = 'frequency',
		minDecibels = -100,
		maxDecibels = -30
	): AudioAnalysisOutputType {
		if (!this.analyser) {
			throw new Error('Not connected, please call .connect() first');
		}
		return AudioAnalysis.getFrequencies(
			this.analyser,
			this.sampleRate,
			null,
			analysisType,
			minDecibels,
			maxDecibels
		);
	}

	/**
	 * Returns the set sample rate of the audio context
	 * @returns {number}
	 */
	getSampleRate(): number {
		if (!this.context) {
			throw new Error('Not connected, please call .connect() first');
		}
		return this.context.sampleRate;
	}

	/**
	 * Sets the output volume (0.0 = muted, 1.0 = full volume)
	 * @param {number} volume
	 */
	setVolume(volume: number): void {
		if (this.gainNode) {
			this.gainNode.gain.value = Math.max(0, Math.min(1, volume));
		}
	}

	/**
	 * Starts audio streaming
	 * @private
	 * @returns {true}
	 */
	private _start(): true {
		if (!this.context) {
			throw new Error('Not connected, please call .connect() first');
		}
		const streamNode = new AudioWorkletNode(this.context, 'stream_processor');
		streamNode.connect(this.gainNode || this.context.destination);
		streamNode.port.onmessage = (e) => {
			const { event } = e.data;
			if (event === 'stop') {
				streamNode.disconnect();
				this.stream = null;
				this.onPlaybackStopped?.();
			} else if (event === 'offset') {
				const { requestId, trackId, offset } = e.data;
				const currentTime = offset / this.sampleRate;
				this.trackSampleOffsets[requestId] = { trackId, offset, currentTime };
			} else if (event === 'audio_part_started') {
				const { trackId, eventId, timestamp } = e.data;
				if (this.onAudioPartStarted) {
					this.onAudioPartStarted({ trackId, eventId, timestamp });
				}
			}
		};
		if (this.analyser) {
			this.analyser?.disconnect();
			streamNode.connect(this.analyser);
		}
		this.stream = streamNode;
		return true;
	}

	/**
	 * Adds 16BitPCM data to the currently playing audio stream
	 * You can add chunks beyond the current play point and they will be queued for play
	 * @param {ArrayBuffer|Int16Array} arrayBuffer
	 * @param {string} [trackId]
	 * @param {string} [eventId]
	 * @returns {Int16Array}
	 */
	add16BitPCM(
		arrayBuffer: ArrayBuffer | Int16Array,
		trackId = 'default',
		eventId = 'default'
	): Int16Array | undefined {
		if (typeof trackId !== 'string') {
			throw new Error(`trackId must be a string`);
		} else if (this.interruptedTrackIds[trackId]) {
			return;
		}
		if (!this.stream) {
			this._start();
		}
		let buffer: Int16Array;
		if (arrayBuffer instanceof Int16Array) {
			buffer = arrayBuffer;
		} else if (arrayBuffer instanceof ArrayBuffer) {
			buffer = new Int16Array(arrayBuffer);
		} else {
			throw new Error(`argument must be Int16Array or ArrayBuffer`);
		}
		this.stream?.port.postMessage({ event: 'write', buffer, trackId, eventId });
		return buffer;
	}

	/**
	 * Gets the offset (sample count) of the currently playing stream
	 * @param {boolean} [interrupt]
	 * @returns {{trackId: string|null, offset: number, currentTime: number}}
	 */
	async getTrackSampleOffset(interrupt = false): Promise<TrackSampleOffset | null> {
		const stream = this.stream;
		if (!stream) {
			return null;
		}
		const requestId = crypto.randomUUID();
		stream.port.postMessage({
			event: interrupt ? 'interrupt' : 'offset',
			requestId
		});
		const timeoutAt = Date.now() + TRACK_SAMPLE_OFFSET_TIMEOUT_MS;
		let trackSampleOffset: TrackSampleOffset | null = null;
		while (!trackSampleOffset) {
			trackSampleOffset = this.trackSampleOffsets[requestId];
			if (trackSampleOffset) {
				break;
			}
			if (this.stream !== stream) {
				return null;
			}
			if (Date.now() >= timeoutAt) {
				return null;
			}
			await new Promise<void>((r) => setTimeout(() => r(), 1));
		}
		delete this.trackSampleOffsets[requestId];
		const { trackId } = trackSampleOffset;
		if (interrupt && trackId) {
			this.interruptedTrackIds[trackId] = true;
		}
		return trackSampleOffset;
	}

	/**
	 * Strips the current stream and returns the sample offset of the audio
	 * @param {boolean} [interrupt]
	 * @returns {{trackId: string|null, offset: number, currentTime: number}}
	 */
	async interrupt(): Promise<TrackSampleOffset | null> {
		return this.getTrackSampleOffset(true);
	}

	/**
	 * Fully tear down the audio graph and release the AudioContext.
	 */
	async close(): Promise<void> {
		if (this.stream) {
			this.stream.disconnect();
			this.stream = null;
		}
		if (this.analyser) {
			this.analyser.disconnect();
			this.analyser = null;
		}
		if (this.gainNode) {
			this.gainNode.disconnect();
			this.gainNode = null;
		}
		this.trackSampleOffsets = {};
		this.interruptedTrackIds = {};
		if (this.context) {
			const context = this.context;
			this.context = null;
			await context.close();
		}
	}
}
