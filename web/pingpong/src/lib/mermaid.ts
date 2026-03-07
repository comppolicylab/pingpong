let mermaidPromise: Promise<typeof import('mermaid').default> | null = null;

export const getMermaid = async () => {
	if (!mermaidPromise) {
		mermaidPromise = import('mermaid')
			.then(({ default: mermaid }) => {
				mermaid.initialize({
					startOnLoad: false,
					theme: 'neutral',
					securityLevel: 'strict'
				});
				return mermaid;
			})
			.catch((error) => {
				mermaidPromise = null;
				throw error;
			});
	}

	return mermaidPromise;
};
