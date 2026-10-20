/** Ask the server to stop, and wait for confirmation of its final database commit. */
export function stopVoiceSession(socket: WebSocket, timeoutMs = 60000): Promise<void> {
	return new Promise((resolve, reject) => {
		const finish = (error?: Error) => {
			clearTimeout(timer);
			socket.removeEventListener('message', onMessage);
			socket.removeEventListener('close', onClose);
			socket.removeEventListener('error', onClose);
			if (error) reject(error);
			else resolve();
		};
		const onMessage = (event: MessageEvent) => {
			if (typeof event.data !== 'string') return;
			let message;
			try {
				message = JSON.parse(event.data);
			} catch {
				return;
			}
			if (message?.type !== 'session.stopped') return;
			finish(
				message.saved === true
					? undefined
					: new Error('The server could not save the voice session.')
			);
		};
		const onClose = () => finish(new Error('The connection closed before the save was confirmed.'));
		const timer = setTimeout(
			() => finish(new Error('The save confirmation timed out.')),
			timeoutMs
		);
		socket.addEventListener('message', onMessage);
		socket.addEventListener('close', onClose);
		socket.addEventListener('error', onClose);
		try {
			if (socket.readyState !== WebSocket.OPEN) {
				finish(new Error('The voice connection is no longer open.'));
				return;
			}
			// Install listeners first: the acknowledgement may arrive immediately.
			socket.send(JSON.stringify({ type: 'session.stop' }));
		} catch (error) {
			finish(error instanceof Error ? error : new Error('Could not end the voice session.'));
		}
	});
}
