<script lang="ts">
	import { resolve } from '$app/paths';

	let { classId }: { classId: string } = $props();
</script>

<a
	href={resolve(`/courses/${classId}`)}
	class="whitespace-nowrap text-primary underline underline-offset-4 hover:text-primary/80"
>
	View course
</a>
