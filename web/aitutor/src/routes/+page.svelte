<script>
  export let data;
</script>

<div>
  <h1>Home</h1>

  <div>{JSON.stringify(data)}</div>

  {#if data.me.user.super_admin}
    <h2>Admin tools</h2>
    <a href="/admin">Admin</a>
  {/if}

</div>
