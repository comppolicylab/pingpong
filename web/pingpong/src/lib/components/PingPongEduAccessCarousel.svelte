<script lang="ts">
	import homework_problems from '$lib/assets/screens/homework_problems.webp';
	import explain_concepts from '$lib/assets/screens/explain_concepts.webp';
	import practice_problems from '$lib/assets/screens/practice_problems.webp';
	import { onMount } from 'svelte';
	import { AngleLeftOutline, AngleRightOutline } from 'flowbite-svelte-icons';
	import { Button, Carousel, Thumbnails, Tooltip } from 'flowbite-svelte';

	let carouselHeight = $state('auto');
	let carouselWidth = $state(0);
	let carouselElement: Element | undefined = $state();

	// Carousel variables
	let index = $state(0);
	let forward = true; // sync animation direction between Thumbnails and Carousel

	const images = [
		{
			alt: 'Screenshot of the Algebra 101 group on the PingPong platform, showing an active thread with the "AI Tutor" assistant discussing a homework problem.',
			src: homework_problems,
			title: 'Homework Problems',
			description:
				'PingPong will help students solve homework problems without giving away answers.'
		},
		{
			alt: 'Screenshot of the Pre-Calculus group on the PingPong platform, showing an active thread with the "Calculus I" assistant discussing the Pythagorean identity.',
			src: explain_concepts,
			title: 'Explain Concepts',
			description: 'PingPong can explain concepts specific to your course content.'
		},
		{
			alt: 'Screenshot of the Statistics 201 group on the PingPong platform displaying a conversation thread with an assistant providing a series of options for practice problem topics.',
			src: practice_problems,
			title: 'Practice Problems',
			description:
				'Students can use PingPong to generate practice problems based on your course syllabus.'
		}
	];

	$effect(() => {
		if (carouselElement && images && carouselWidth > 0) {
			const img = new Image();
			img.onload = () => {
				const aspectRatio = img.height / img.width;
				carouselHeight = `${carouselWidth * aspectRatio}px`;
			};
			img.src = images[index].src;
		}
	});

	onMount(() => {
		if (!carouselElement) return;
		const resizeObserver = new ResizeObserver((entries) => {
			for (let entry of entries) {
				carouselWidth = entry.contentRect.width;
			}
		});

		resizeObserver.observe(carouselElement);

		return () => {
			resizeObserver.disconnect();
		};
	});
</script>

<div bind:this={carouselElement} class="rounded-lg pb-5">
	<Carousel
		{images}
		{forward}
		let:Controls
		bind:index
		imgClass="w-full"
		style="height: {carouselHeight}"
	>
		<Controls let:changeSlide>
			<Button
				pill
				class="absolute start-4 top-1/2 -translate-y-1/2 bg-blue-light-50 p-2 font-bold text-blue-dark-40 opacity-90 hover:opacity-100"
				onclick={() => changeSlide(false)}><AngleLeftOutline /></Button
			>
			<Button
				pill
				class="absolute end-4 top-1/2 -translate-y-1/2 bg-blue-light-50 p-2 font-bold text-blue-dark-40 opacity-90 hover:opacity-100"
				onclick={() => changeSlide(true)}><AngleRightOutline /></Button
			>
		</Controls>
	</Carousel>
	<div class="my-2 mb-4 rounded-sm border-2 border-blue-light-40 bg-blue-light-50 p-2 text-center">
		{images[index].description}
	</div>
	<Thumbnails class="gap-3 bg-transparent" let:Thumbnail let:image let:selected {images} bind:index>
		{@const image_lte = { src: image.src, alt: image.alt }}
		<Thumbnail
			{...image_lte}
			{selected}
			class="h-24 rounded-md shadow-xl hover:outline hover:outline-orange-dark"
			activeClass="outline outline-orange"
		/>
		<Tooltip
			defaultClass="text-wrap py-2 px-3 text-sm font-normal shadow-xs"
			placement="bottom"
			arrow={false}>{image.title}</Tooltip
		>
	</Thumbnails>
</div>
