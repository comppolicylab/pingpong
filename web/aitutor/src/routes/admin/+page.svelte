<script>
  import { Button, Label, Input, Heading } from "flowbite-svelte";
  import { enhance } from "$app/forms";
  export let data;
</script>

<div>
  <Heading tag="h1">Admin</Heading>

  <Heading tag="h2">Institutions</Heading>
  <ul>
    {#each data.institutions as institution}
      <li>
        <a href="/admin/institution/{institution.id}">
          {institution.name}
        </a>
      </li>
    {/each}
  </ul>

  <Heading tag="h2">Create a new institution</Heading>
  <form action="/admin?/createInstitution" method="POST" use:enhance>
    <Label for="name">Name</Label>
    <Input type="text" name="name" id="name" />
    <Button type="submit">Create</Button>
  </form>
</div>
