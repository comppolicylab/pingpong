import { describe, expect, it, vi } from 'vitest';
import { AudioProcessorWorklet } from './audio_processor';

type Processor = {
	chunks: Float32Array[][];
	port: {
		onmessage: ((event: { data: object }) => void) | null;
		postMessage: ReturnType<typeof vi.fn>;
	};
	process: (inputs: Float32Array[][], outputs: Float32Array[][], parameters: object) => boolean;
};

function createProcessor() {
	let ProcessorClass: (new () => Processor) | null = null;
	class FakeAudioWorkletProcessor {
		port = { onmessage: null, postMessage: vi.fn() };
	}
	new Function('AudioWorkletProcessor', 'registerProcessor', AudioProcessorWorklet)(
		FakeAudioWorkletProcessor,
		(_name: string, registered: new () => Processor) => {
			ProcessorClass = registered;
		}
	);
	if (!ProcessorClass) throw new Error('AudioProcessor was not registered');
	return new (ProcessorClass as new () => Processor)();
}

describe('microphone AudioProcessor worklet', () => {
	it.each([false, true])(
		'streams PCM with streamingOnly=%s and retains audio only when requested',
		(streamingOnly) => {
			const processor = createProcessor();
			processor.port.onmessage?.({ data: { event: 'start', id: 1, data: { streamingOnly } } });
			const samples = new Float32Array(128).fill(0.5);
			for (let i = 0; i < 1000; i++) processor.process([[samples]], [], {});
			expect(processor.chunks.length).toBe(streamingOnly ? 0 : 1000);
			const chunks = processor.port.postMessage.mock.calls
				.map(([data]) => data)
				.filter((data) => data.event === 'chunk');
			expect(chunks).toHaveLength(1000);
			expect(new Int16Array(chunks[0].data.mono)).toEqual(new Int16Array(128).fill(16383));
			processor.port.onmessage?.({ data: { event: 'stop', id: 2 } });
			processor.port.postMessage.mockClear();
			processor.process([[samples]], [], {});
			expect(processor.port.postMessage).not.toHaveBeenCalled();
		}
	);
});
