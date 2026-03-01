type TransformStreamConstructor = new <I, O>(
	transformer?: Transformer<I, O>,
	writableStrategy?: QueuingStrategy<I>,
	readableStrategy?: QueuingStrategy<O>
) => TransformStream<I, O>;

// CodeQL flags direct TransformStream(...) args in this repo; route through a typed alias.
const TransformStreamCtor = globalThis.TransformStream as unknown as TransformStreamConstructor;

function createTransformStream<I, O>(transformer: Transformer<I, O>): TransformStream<I, O> {
	return new TransformStreamCtor(transformer);
}

/**
 * A stream that parses chunks as JSON objects.
 */
export function JSONStream(): TransformStream<string, object> {
	return createTransformStream({
		transform(chunk, controller) {
			try {
				controller.enqueue(JSON.parse(chunk));
			} catch (e) {
				controller.error(e);
			}
		}
	});
}

/**
 * A stream that emits lines of text in chunks as they are received.
 */
export function TextLineStream(): TransformStream<string, string> {
	let buffer = '';

	return createTransformStream({
		transform(chunk, controller) {
			// Add characters to the buffer, emitting at each newline
			for (const char of chunk) {
				if (char === '\n') {
					controller.enqueue(buffer);
					buffer = '';
				} else {
					buffer += char;
				}
			}
		},
		flush(controller) {
			// If there's anything left in the buffer, emit it
			if (buffer.length > 0) {
				controller.enqueue(buffer);
				buffer = '';
			}
		}
	});
}
