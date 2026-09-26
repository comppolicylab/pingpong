<script lang="ts">
	let {
		src,
		alt,
		onready,
		onerror
	}: {
		src: string;
		alt: string;
		onready: (image: HTMLImageElement) => void;
		onerror: () => void;
	} = $props();

	function prepare(image: HTMLImageElement) {
		let cancelled = false;
		void image
			.decode()
			.then(() => {
				if (!cancelled) onready(image);
			})
			.catch(() => {
				if (!cancelled) onerror();
			});
		return () => {
			cancelled = true;
		};
	}
</script>

<img {src} {alt} {@attach prepare} class="h-full w-full object-contain" />
