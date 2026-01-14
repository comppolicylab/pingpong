<script lang="ts">
	import { resolve } from '$app/paths';
</script>

<!-- We don't really expect anyone to ever see this page.
  -- Just add some loose directions in case we're wrong about that!
  -->
<div class="m-auto flex flex-col gap-4 p-16">
	<h1 class="text-2xl">Welcome to PingPong!</h1>
	<p>It looks like you have not been added to any group and you are also not an admin.</p>
	<p>
		This suggests something might be misconfigured. Please contact your site admin, or see our <a
			href={resolve('/about')}
			class="text-orange hover:text-orange-dark">about</a
		> page for more help.
	</p>
</div>
