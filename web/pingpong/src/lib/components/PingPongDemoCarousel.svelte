<script lang="ts">
  import chat_screen from '$lib/assets/screens/chat_v2.webp';
  import edit_assistant_screen from '$lib/assets/screens/edit_assistant_v2.webp';
  import group_home from '$lib/assets/screens/group_home_v2.webp';
  import home_screen from '$lib/assets/screens/home_v3.webp';
  import { onMount } from 'svelte';
  import { AngleLeftOutline, AngleRightOutline } from 'flowbite-svelte-icons';
  import { Button, Carousel, Thumbnails, Tooltip } from 'flowbite-svelte';

  let carouselHeight = 'auto';
  let carouselWidth = 0;
  let carouselElement: Element;

  // Carousel variables
  let index = 0;
  let forward = true; // sync animation direction between Thumbnails and Carousel

  const images = [
    {
      alt: 'Screenshot of the Public Policy Class group on the PingPong platform with a selected assistant titled "Reading Help" and a sidebar showing various previous threads.',
      src: home_screen,
      title: 'Home Screen',
      description: 'Start a new chat with an assistant or view previous threads.'
    },
    {
      alt: 'Screenshot of the Public Policy Class group on the PingPong platform, showing an active thread with the "Practice Problem Generator" assistant and sidebar showing various previous threads.',
      src: chat_screen,
      title: 'Chats',
      description: 'View and interact with past threads and continue the conversation at any time.'
    },
    {
      alt: 'Screenshot of the Public Policy Class group on the PingPong platform, featuring options to create a new assistant and manage existing ones for Reading Help, Weekly Check-In, and Policy Debate Prep.',
      src: group_home,
      title: 'Group Home',
      description:
        'Create and manage assistants for your group in minutes. Manage permissions and access to documents.'
    },
    {
      alt: 'Screenshot of the Public Policy Class group on the PingPong platform, showing the Edit Assistant screen with options to choose a model, input a prompt, and add or remove documents.',
      src: edit_assistant_screen,
      title: 'Edit Assistants',
      description:
        'Customize your assistant with your custom prompt and documents. Select the model that best fits your needs.'
    }
  ];

  $: if (carouselElement && images && carouselWidth > 0) {
    const img = new Image();
    img.onload = () => {
      const aspectRatio = img.height / img.width;
      carouselHeight = `${carouselWidth * aspectRatio}px`;
    };
    img.src = images[index].src;
  }

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
        class="p-2 bg-blue-light-50 opacity-90 hover:opacity-100 text-blue-dark-40 absolute top-1/2 -translate-y-1/2 start-4 font-bold"
        on:click={() => changeSlide(false)}><AngleLeftOutline /></Button
      >
      <Button
        pill
        class="p-2 bg-blue-light-50 opacity-90 hover:opacity-100 text-blue-dark-40 absolute top-1/2 -translate-y-1/2 end-4 font-bold"
        on:click={() => changeSlide(true)}><AngleRightOutline /></Button
      >
    </Controls>
  </Carousel>
  <div class="rounded border-2 border-blue-light-40 bg-blue-light-50 p-2 my-2 mb-4 text-center">
    {images[index].description}
  </div>
  <Thumbnails class="bg-transparent gap-3" let:Thumbnail let:image let:selected {images} bind:index>
    {@const image_lte = { src: image.src, alt: image.alt }}
    <Thumbnail
      {...image_lte}
      {selected}
      class="h-24 rounded-md shadow-xl hover:outline hover:outline-orange-dark"
      activeClass="outline outline-orange"
    />
    <Tooltip
      defaultClass="text-wrap py-2 px-3 text-sm font-normal shadow-sm"
      placement="bottom"
      arrow={false}>{image.title}</Tooltip
    >
  </Thumbnails>
</div>
