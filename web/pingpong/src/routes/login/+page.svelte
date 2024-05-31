<script lang="ts">
  import type { SubmitFunction } from '@sveltejs/kit';
  import { enhance } from '$app/forms';
  import PingPongLogo from '$lib/components/PingPongLogo.svelte';
  import { Button, P, InputAddon, Input, Helper, Heading, ButtonGroup } from 'flowbite-svelte';
  import { EnvelopeSolid } from 'flowbite-svelte-icons';
  import { writable } from 'svelte/store';
  import { fail } from '@sveltejs/kit';
  import { sadToast } from '$lib/toast';
  import * as api from '$lib/api';

  export let form;

  const loggingIn = writable(false);
  const success = writable(false);
  const loginWithMagicLink = async (evt: SubmitEvent) => {
    evt.preventDefault();
    loggingIn.set(true);

    const form = evt.target as HTMLFormElement;
    const formData = new FormData(form);
    const d = Object.fromEntries(formData.entries());

    const email = d.email?.toString();
    if (!email) {
      return fail(400, { email, success: false, error: 'Missing email' });
    }

    const result = await api.loginWithMagicLink(fetch, email);
    if (result.$status < 300) {
      success.set(true);
      loggingIn.set(false);
    } else {
      sadToast(result.detail?.toString() || 'Could not log in');
      loggingIn.set(false);
    }
  }
</script>

<div class="h-[calc(100dvh-3rem)] v-screen flex items-center justify-center">
  <div class="flex flex-col w-11/12 lg:w-6/12 max-w-2xl rounded-4xl overflow-hidden">
    <header class="bg-blue-dark-40 px-12 py-8">
      <Heading tag="h1" class="logo w-full text-center"><PingPongLogo size="full" /></Heading>
    </header>
    <div class="px-12 py-16 bg-white">
      {#if $success}
        <div class="text-orange">Success! Follow the link in your email to finish signing in.</div>
      {:else}
        <form on:submit={loginWithMagicLink}>
          <ButtonGroup class="w-full rounded-full bg-blue-light-50 shadow-inner p-4">
            <InputAddon class="rounded-none border-none bg-transparent text-blue-light-40">
              <EnvelopeSolid />
            </InputAddon>
            <Input
              value={form?.email ?? ''}
              readonly={$loggingIn || null}
              type="email"
              placeholder="you@school.edu"
              name="email"
              id="email"
              class="bg-transparent border-none"
            ></Input>
            <Button
              pill
              class="p-3 px-6 mr-2 rounded-full bg-orange text-white hover:bg-orange-dark"
              type="submit"
              disabled={$loggingIn}>Login</Button
            >
          </ButtonGroup>
          {#if form?.error}
            <div class="p-2">
              <P class="text-orange">We could not sign you in.</P>
              <P class="text-orange"
                >Please make sure you are using the correct email address and try again.
              </P>
            </div>
          {:else}
            <Helper class="my-2 text-black text-sm">Log in with your school email address.</Helper>
          {/if}
        </form>
      {/if}
    </div>
  </div>
</div>
