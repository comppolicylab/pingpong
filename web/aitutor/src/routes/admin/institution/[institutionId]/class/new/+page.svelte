<script>
  import { Label, Input, Button, Heading } from 'flowbite-svelte';

  export let data;
</script>

<div>
  <Heading>New Class</Heading>
  <div>
    <form action="/admin/institution/{data.institution_id}/class/new?/createClass" method="POST">
      <Label for="name">Name</Label>
      <Input type="text" name="name" id="name" placeholder="Name" />
      <Label for="term">Term</Label>
      <Input type="text" name="term" id="term" placeholder="Term" />
      <div>
        <Button type="submit">Create</Button>
      </div>
    </form>
  </div>
</div>
