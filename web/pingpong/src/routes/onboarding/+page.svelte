<script lang="ts">
  import { page } from '$app/stores';
  import { Input, Button, Heading } from 'flowbite-svelte';
  import * as api from '$lib/api';
  import { happyToast, sadToast } from '$lib/toast';
  import { goto } from '$app/navigation';
  import PingPongLogo from '$lib/components/PingPongLogo.svelte';

  export let data;

  let loading = false;

  const saveName = async (event: SubmitEvent) => {
    event.preventDefault();
    const form = event.target as HTMLFormElement | undefined;
    if (!form) {
      return;
    }
    loading = true;
    const formData = new FormData(form);
    const first_name = formData.get('firstName')?.toString();
    const last_name = formData.get('lastName')?.toString();

    if (!first_name || !last_name) {
      loading = false;
      return sadToast('Please enter your first and last name');
    }

    const response = await api.updateUserInfo(fetch, { first_name, last_name });
    const expanded = api.expandResponse(response);
    if (expanded.error) {
      sadToast(`Failed to profile information: ${expanded.error.detail}`);
    } else {
      happyToast('Profile information saved');
      // Get `forward` parameter from URL
      const destination = $page.url.searchParams.get('forward') || '/';
      // eslint-disable-next-line svelte/no-navigation-without-resolve
      await goto(destination, { invalidateAll: true });
    }
    loading = false;
  };
</script>

<div class="h-[calc(100dvh-3rem)] v-screen flex items-center justify-center">
  <div class="flex flex-col w-11/12 lg:w-6/12 max-w-2xl rounded-4xl overflow-hidden">
    <header class="bg-blue-dark-40 px-12 py-8">
      <Heading tag="h1" class="logo w-full text-center"><PingPongLogo size="full" /></Heading>
    </header>
    <div class="px-8 py-8 bg-white">
      <form on:submit={saveName}>
        <section class="flex flex-col gap-2">
          <div class="w-full text-md">
            Welcome, {data.me.user?.email || 'Unknown'}.
          </div>
          <div class="w-full text-xs mb-6">Please enter your name to continue.</div>
          <div>
            <Input
              type="text"
              placeholder="First name / given name"
              name="firstName"
              value={data.me.user?.first_name || ''}
              disabled={loading}
            />
          </div>
          <div>
            <Input
              type="text"
              placeholder="Surname / family name"
              name="lastName"
              value={data.me.user?.last_name || ''}
              disabled={loading}
            />
          </div>
          <div class="text-center flex justify-end mt-4">
            <Button
              type="submit"
              class="text-white bg-orange rounded-full hover:bg-orange-dark"
              disabled={loading}>Continue to PingPong</Button
            >
          </div>
        </section>
      </form>
    </div>
  </div>
</div>
