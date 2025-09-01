<script lang="ts">
	let { classId }: { classId: string } = $props();
</script>

<a
	href={`/courses/${classId}`}
	class="whitespace-nowrap text-primary underline underline-offset-4 hover:text-primary/80"
>
	View course
</a>
