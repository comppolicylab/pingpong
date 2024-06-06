<script lang="ts">
  import { page } from '$app/stores';
  import { Input, Button, Heading } from 'flowbite-svelte';
  import * as api from '$lib/api';
  import { happyToast, sadToast } from '$lib/toast';
  import { goto } from '$app/navigation';

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
      // Get `forward` parametr from URL
      const destination = $page.url.searchParams.get('forward') || '/';
      await goto(destination, { invalidateAll: true });
    }
    loading = false;
  };
</script>

<div class="w-full h-full flex align-center justify-center">
  <div class="m-auto w-[30rem] bg-white rounded-2xl">
    <div class="bg-orange rounded-t-2xl">
      <Heading tag="h1" customSize="text-4xl" class="px-16 py-8 w-full text-center text-white"
        >PingPong.</Heading
      >
    </div>
    <div class="px-8 py-4">
      <form on:submit={saveName}>
        <section class="flex flex-col gap-4">
          <div class="w-full text-center">
            Welcome, {data.me.user?.email || 'Unknown'}.
          </div>
          <div class="w-full text-center">Please enter your name to continue.</div>
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
          <div class="text-center">
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
