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
import { ensureStreamProcessorModule } from './shared_audio_context';

export type OnAudioPartStartedProcessor = (data: {
	trackId: string;
	eventId: string;
	timestamp: number;
}) => void;
export type OnAudioPartEndedProcessor = (data: {
	trackId: string;
	eventId: string;
	timestamp: number;
}) => void;
export type OnPlaybackStoppedProcessor = () => void;
export type PlaybackSettled = {
	trackId: string;
	outcome: 'completed' | 'interrupted' | 'discarded';
	played: boolean;
};
interface WavStreamPlayerOptions {
	sampleRate?: number;
	/**
	 * Externally owned AudioContext to play through (e.g. one unlocked during a
	 * user gesture). Its sampleRate must match `sampleRate`; otherwise the
	 * player falls back to creating its own context. A provided context is
	 * never closed by this player.
	 */
	context?: AudioContext;
	stopOnEmptyBuffer?: boolean;
	onAudioPartStarted?: OnAudioPartStartedProcessor;
	onAudioPartEnded?: OnAudioPartEndedProcessor;
	onPlaybackStopped?: OnPlaybackStoppedProcessor;
	onPlaybackSettled?: (data: PlaybackSettled) => void;
}

interface TrackSampleOffset {
	trackId: string | null;
	offset: number;
	currentTime: number;
	eventId?: string | null;
}

const TRACK_SAMPLE_OFFSET_TIMEOUT_MS = 250;

/**
 * Plays audio streams received in raw PCM16 chunks from the browser
 * @class
 */
export class WavStreamPlayer {
	private scriptSrc: string;
	private sampleRate: number;
	private providedContext: AudioContext | null;
	private ownsContext: boolean;
	private context: AudioContext | null;
	private stream: AudioWorkletNode | null;
	private analyser: AnalyserNode | null;
	private gainNode: GainNode | null;
	private trackSampleOffsets: Record<string, TrackSampleOffset>;
	private interruptedTrackIds: Record<string, boolean>;
	private stopOnEmptyBuffer: boolean;
	private onAudioPartStarted: OnAudioPartStartedProcessor | null;
	private onAudioPartEnded: OnAudioPartEndedProcessor | null;
	private onPlaybackStopped: OnPlaybackStoppedProcessor | null;
	private onPlaybackSettled: ((data: PlaybackSettled) => void) | null;
	private pendingTrackIds = new Set<string>();
	private playedTrackIds = new Set<string>();
	private settledTrackIds = new Set<string>();
	private streamTracks = new Map<AudioWorkletNode, Set<string>>();
	private interruptingStreams = new Set<AudioWorkletNode>();
	private pendingInterrupts = new Set<Promise<TrackSampleOffset | null>>();
	private closed = false;

	/**
	 * Creates a new WavStreamPlayer instance
	 * @param {{sampleRate?: number, onAudioPartStarted?: OnAudioPartStartedProcessor}} options
	 * @returns {WavStreamPlayer}
	 */
	constructor({
		sampleRate = 44100,
		context,
		stopOnEmptyBuffer = true,
		onAudioPartStarted,
		onAudioPartEnded,
		onPlaybackStopped,
		onPlaybackSettled
	}: WavStreamPlayerOptions = {}) {
		this.scriptSrc = StreamProcessorSrc;
		this.sampleRate = sampleRate;
		this.providedContext = context ?? null;
		this.ownsContext = true;
		this.context = null;
		this.stream = null;
		this.analyser = null;
		this.gainNode = null;
		this.trackSampleOffsets = {};
		this.interruptedTrackIds = {};
		this.stopOnEmptyBuffer = stopOnEmptyBuffer;
		this.onAudioPartStarted = onAudioPartStarted || null;
		this.onAudioPartEnded = onAudioPartEnded || null;
		this.onPlaybackStopped = onPlaybackStopped || null;
		this.onPlaybackSettled = onPlaybackSettled || null;
	}

	/**
	 * Connects the audio context and enables output to speakers
	 * @returns {Promise<true>}
	 */
	async connect(): Promise<true> {
		if (!isAudioWorkletSupported()) {
			throw new Error(AUDIO_WORKLET_UNSUPPORTED_MESSAGE);
		}

		if (
			this.providedContext &&
			this.providedContext.state !== 'closed' &&
			this.providedContext.sampleRate === this.sampleRate
		) {
			this.context = this.providedContext;
			this.ownsContext = false;
		} else {
			if (
				this.providedContext &&
				this.providedContext.state !== 'closed' &&
				this.providedContext.sampleRate !== this.sampleRate
			) {
				console.warn(
					`Provided AudioContext sample rate ${this.providedContext.sampleRate} does not match ${this.sampleRate}; creating a dedicated context.`
				);
			}
			this.context = new AudioContext({ sampleRate: this.sampleRate });
			this.ownsContext = true;
		}
		if (this.context.state === 'suspended') {
			await this.context.resume();
		}
		try {
			await ensureStreamProcessorModule(this.context);
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
		this.streamTracks.set(streamNode, new Set());
		streamNode.connect(this.gainNode || this.context.destination);
		// This is queued before any write messages, so the worklet sees this
		// configuration before it can process streamed PCM.
		streamNode.port.postMessage({
			event: 'configure',
			stopOnEmptyBuffer: this.stopOnEmptyBuffer
		});
		streamNode.port.onmessage = (e) => {
			if (this.closed) return;
			const { event } = e.data;
			if (event === 'stop') {
				this._handlePlaybackStopped(streamNode);
			} else if (event === 'offset') {
				const { requestId, trackId, offset, eventId } = e.data;
				const currentTime = offset / this.sampleRate;
				this.trackSampleOffsets[requestId] = {
					trackId,
					offset,
					currentTime,
					eventId
				};
			} else if (event === 'audio_part_started') {
				const { trackId, eventId, timestamp } = e.data;
				this.playedTrackIds.add(trackId);
				if (this.onAudioPartStarted) {
					this.onAudioPartStarted({ trackId, eventId, timestamp });
				}
			} else if (event === 'audio_part_ended') {
				const { trackId, eventId, timestamp } = e.data;
				this.playedTrackIds.add(trackId);
				if (this.onAudioPartEnded) {
					this.onAudioPartEnded({ trackId, eventId, timestamp });
				}
			} else if (event === 'track_settled') {
				this.settleTrack(e.data);
			}
		};
		if (this.analyser) {
			this.analyser?.disconnect();
			streamNode.connect(this.analyser);
		}
		this.stream = streamNode;
		return true;
	}

	private _handlePlaybackStopped(streamNode: AudioWorkletNode | null): void {
		streamNode?.disconnect();
		if (streamNode) {
			this.streamTracks.delete(streamNode);
			this.interruptingStreams.delete(streamNode);
		}
		if (this.stream && streamNode && this.stream !== streamNode) return;
		if (!streamNode || this.stream === streamNode) {
			this.stream = null;
		}
		this.onPlaybackStopped?.();
	}

	private settleTrack(data: PlaybackSettled): void {
		if (!this.pendingTrackIds.has(data.trackId) || this.settledTrackIds.has(data.trackId)) return;
		this.settledTrackIds.add(data.trackId);
		this.pendingTrackIds.delete(data.trackId);
		this.onPlaybackSettled?.({ trackId: data.trackId, outcome: data.outcome, played: data.played });
	}

	/** Mark this reply's generation finished; playback may still be queued. */
	finishTrack(trackId: string): void {
		if (this.closed || this.settledTrackIds.has(trackId) || this.interruptedTrackIds[trackId])
			return;
		this.pendingTrackIds.add(trackId);
		if (!this.stream) {
			const played = this.playedTrackIds.has(trackId);
			this.settleTrack({ trackId, outcome: played ? 'completed' : 'discarded', played });
			return;
		}
		this.streamTracks.get(this.stream)?.add(trackId);
		this.stream.port.postMessage({ event: 'finish_track', trackId });
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
		} else if (
			this.closed ||
			this.interruptedTrackIds[trackId] ||
			this.settledTrackIds.has(trackId)
		) {
			return;
		}
		let buffer: Int16Array;
		if (arrayBuffer instanceof Int16Array) {
			buffer = arrayBuffer;
		} else if (arrayBuffer instanceof ArrayBuffer) {
			buffer = new Int16Array(arrayBuffer);
		} else {
			throw new Error(`argument must be Int16Array or ArrayBuffer`);
		}
		if (!buffer.length) return buffer;
		if (!this.stream) {
			this._start();
		}
		this.pendingTrackIds.add(trackId);
		if (this.stream) this.streamTracks.get(this.stream)?.add(trackId);
		this.stream?.port.postMessage({ event: 'write', buffer, trackId, eventId });
		return buffer;
	}

	/**
	 * Signals that no more PCM chunks will be written.
	 */
	finish(): void {
		if (!this.stream) {
			this._handlePlaybackStopped(null);
			return;
		}
		this.stream.port.postMessage({ event: 'finish' });
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
		if (interrupt) {
			// Fence every reply already posted to this stream before yielding.
			// New replies get a new stream; old replies cannot resume on it.
			for (const trackId of this.streamTracks.get(stream) ?? []) {
				this.interruptedTrackIds[trackId] = true;
			}
			this.interruptingStreams.add(stream);
			this.stream = null;
		}
		stream.port.postMessage({
			event: interrupt ? 'interrupt' : 'offset',
			requestId
		});
		const timeoutAt = Date.now() + TRACK_SAMPLE_OFFSET_TIMEOUT_MS;
		let trackSampleOffset: TrackSampleOffset | null;
		while (true) {
			trackSampleOffset = this.trackSampleOffsets[requestId];
			if (trackSampleOffset) {
				break;
			}
			if (interrupt ? !this.interruptingStreams.has(stream) : this.stream !== stream) {
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
		// A second caller (for example End during barge-in) must wait for the
		// first receipt too, without sending a duplicate interrupt/truncate.
		const pending = [...this.pendingInterrupts];
		const current = this.stream ? this.getTrackSampleOffset(true) : null;
		if (current) this.pendingInterrupts.add(current);
		try {
			const results = await Promise.all(current ? [...pending, current] : pending);
			return current ? (results.at(-1) ?? null) : null;
		} finally {
			if (current) this.pendingInterrupts.delete(current);
		}
	}

	/**
	 * Fully tear down the audio graph and release the AudioContext.
	 */
	async close(): Promise<void> {
		this.closed = true;
		for (const stream of this.interruptingStreams) stream.disconnect();
		this.interruptingStreams.clear();
		this.streamTracks.clear();
		this.pendingTrackIds.clear();
		this.playedTrackIds.clear();
		this.settledTrackIds.clear();
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
			// A provided (shared) context outlives this player.
			if (this.ownsContext) {
				await context.close();
			}
		}
	}
}
