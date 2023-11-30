<script>
  import { enhance } from "$app/forms";
  export let data;
</script>

<div>
  <h1>Admin</h1>

  <h2>Create a new institution</h2>
  <form action="/admin?/createInstitution" method="POST" use:enhance>
    <label for="name">Name</label>
    <input type="text" name="name" id="name" />
    <button type="submit">Create</button>
  </form>
</div>
