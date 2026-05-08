import { describe, expect, it, vi } from 'vitest';

import { StreamProcessorWorklet } from './stream_processor';

type ProcessorConstructor = new () => {
	port: {
		onmessage: ((event: { data: object }) => void) | null;
		postMessage: ReturnType<typeof vi.fn>;
	};
	process: (_inputs: unknown[], outputs: Float32Array[][], _parameters: object) => boolean;
};

const createProcessor = () => {
	let Processor: ProcessorConstructor | null = null;
	class FakeAudioWorkletProcessor {
		port = {
			onmessage: null as ((event: { data: object }) => void) | null,
			postMessage: vi.fn()
		};
	}
	const registerProcessor = (_name: string, processor: ProcessorConstructor) => {
		Processor = processor;
	};

	new Function('AudioWorkletProcessor', 'registerProcessor', StreamProcessorWorklet)(
		FakeAudioWorkletProcessor,
		registerProcessor
	);
	if (!Processor) {
		throw new Error('StreamProcessor was not registered');
	}
	const RegisteredProcessor = Processor as ProcessorConstructor;
	return new RegisteredProcessor();
};

const writePcm = (
	processor: ReturnType<typeof createProcessor>,
	sampleCount: number,
	trackId: string,
	eventId: string
) => {
	processor.port.onmessage?.({
		data: {
			event: 'write',
			buffer: new Int16Array(sampleCount),
			trackId,
			eventId
		}
	});
};

const processOnce = (processor: ReturnType<typeof createProcessor>) => {
	processor.process([], [[new Float32Array(128)]], {});
};

const postedMessages = (processor: ReturnType<typeof createProcessor>) =>
	(processor.port.postMessage.mock.calls as [Record<string, unknown>][]).map(
		([message]) => message
	);

describe('StreamProcessor worklet', () => {
	it('does not count padded render frames as played audio samples', () => {
		const processor = createProcessor();

		writePcm(processor, 129, 'track-1', 'event-1');
		processOnce(processor);
		processOnce(processor);
		processOnce(processor);

		processor.port.onmessage?.({
			data: { event: 'offset', requestId: 'request-1' }
		});

		const offsetMessage = postedMessages(processor).find(
			(message: Record<string, unknown>) => message.event === 'offset'
		);
		expect(offsetMessage).toMatchObject({
			requestId: 'request-1',
			trackId: 'track-1',
			offset: 129,
			eventId: 'event-1'
		});
	});

	it('reports the currently playing track instead of the latest written track on interrupt', () => {
		const processor = createProcessor();

		writePcm(processor, 128, 'track-1', 'event-1');
		processOnce(processor);
		writePcm(processor, 128, 'track-2', 'event-2');

		processor.port.onmessage?.({
			data: { event: 'interrupt', requestId: 'request-1' }
		});

		const offsetMessage = postedMessages(processor).find(
			(message: Record<string, unknown>) => message.event === 'offset'
		);
		expect(offsetMessage).toMatchObject({
			requestId: 'request-1',
			trackId: 'track-1',
			offset: 128,
			eventId: 'event-1'
		});
	});
});
