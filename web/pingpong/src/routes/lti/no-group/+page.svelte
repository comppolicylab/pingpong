<script lang="ts">
  import { Button, Heading } from 'flowbite-svelte';
  import { goto } from '$app/navigation';
  import PingPongLogo from '$lib/components/PingPongLogo.svelte';
  import { loading } from '$lib/stores/general.js';
  import { resolve } from '$app/paths';

  const continueToPingPong = async () => {
    $loading = true;
    await goto(resolve('/'));
    $loading = false;
  };
</script>

<div class="h-[calc(100dvh-3rem)] v-screen flex items-center justify-center">
  <div class="flex flex-col w-11/12 lg:w-7/12 max-w-2xl rounded-4xl overflow-hidden">
    <header class="bg-blue-dark-40 px-12 py-8">
      <Heading tag="h1" class="logo w-full text-center"><PingPongLogo size="full" /></Heading>
    </header>
    <div class="px-12 py-8 bg-white">
      <div class="flex flex-col gap-4">
        <div class="w-full font-medium text-3xl mb-2">This course isn't on PingPong yet.</div>
        <div class="w-full flex flex-col gap-4">
          <p class="text-md">
            Your instructor hasn&apos;t linked this Canvas course to a PingPong group, so there
            isn&apos;t a class space to enter.
          </p>
          <p class="text-md">
            Please ask your instructor to complete the setup. In the meantime, you can continue to
            the main PingPong page.
          </p>
        </div>
        <div class="flex-row gap-4 text-center flex justify-end mt-4">
          <Button
            type="button"
            class="text-white bg-orange rounded-full hover:bg-orange-dark"
            onclick={continueToPingPong}
            disabled={$loading}>Continue</Button
          >
        </div>
      </div>
    </div>
  </div>
</div>
