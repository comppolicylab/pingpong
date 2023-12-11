<script lang="ts">
  import {enhance} from "$app/forms";
  import logo from '../../logo.svg?raw';
  import {P, A, InputAddon, Input, Label, GradientButton, Button, Heading, ButtonGroup} from 'flowbite-svelte';
  import {EnvelopeSolid} from 'flowbite-svelte-icons';

  export let form;
  let loggingIn = false;
  $: {
    if (form) {
      loggingIn = false;
    }
}
</script>

<div class="h-screen v-screen flex items-center justify-center">
  <div class="flex items-center justify-center flex-col">
    <div class="w-20 fill-amber-600">
      <div class:animate-spin="{loggingIn}">
      {@html logo}
        </div>
    </div>
    <div class="mt-4">
      <Heading tag="h1" class="text-amber-500">AI Tutor</Heading>
    </div>
    <div class="mt-8 w-90">
      {#if form?.success}
        {#if form?.magicLink}
          <div class="text-amber-300">
            <P class="text-amber-300">[ Since the app is currently in development mode, you can <A href="{form.magicLink}" class="text-green-300 underline">click here</A> to finish signing in. ]</P>
              <P class="text-amber-300">Normally, you would see the following message:</P>
          </div>
        <div class="text-green-300">Success! Follow the link in your email to finish signing in.</div>
        {/if}
      {:else}
      <form action="/login?/loginWithMagicLink" method="POST" use:enhance>
          <Label for="email" class="mb-2 text-white">Log in with your school email address:</Label>
            <ButtonGroup class="w-full">
              <InputAddon>
              <EnvelopeSolid />
              </InputAddon>
              <Input value={form?.email ?? ''} type="email" placeholder="you@school.edu" name="email" id="email">
            </Input>
              <GradientButton type="submit" color="cyanToBlue" on:click={() => loggingIn = true}>Login</GradientButton>
            </ButtonGroup>
          {#if form?.error}
            <div class="text-red-500 p-2">
              <P>
                We could not sign you in.
              </P>
              <P>Please make sure you are using the correct email address and try again.
              </P>
            </div>
          {/if}
          </form>
      {/if}
    </div>
  </div>
</div>
