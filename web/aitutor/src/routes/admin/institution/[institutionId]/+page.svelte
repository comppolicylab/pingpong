<script>
  import { Heading } from 'flowbite-svelte';

  export let data;
</script>

<div>
  <Heading>Institution: {data.institution.name}</Heading>

  <Heading tag="h2">Classes</Heading>
  <ul>
    {#each data.classes as class_}
      <li>
        <a href="/admin/institution/{data.institution.id}/class/{class_.id}">{class_.name}</a>
      </li>
    {/each}
  </ul>
  <div>
    <a href="/admin/institution/{data.institution.id}/class/new">Add new class</a>
  </div>
</div>
