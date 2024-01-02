<script lang="ts">
  import {createEventDispatcher} from 'svelte';
  import {Heading} from "flowbite-svelte";

  const dispatch = createEventDispatcher();

  export let user;
</script>

<div class="cursor-pointer w-full" on:click={() => dispatch('click')}>
  <Heading tag="h5" customSize="text-lg">{user.email}</Heading>
  <div class="flex justify-between pointer-events-none w-full">
    <div>{user.title}</div>
    <div>{user.role}</div>
    <div>{user.state}</div>
  </div>
</div>
