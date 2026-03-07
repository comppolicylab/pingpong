<script lang="ts">
	export let source = '';
</script>

<div
	class="mermaid-block not-prose relative mb-4 overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm"
>
	<div
		class="flex items-center justify-between gap-3 border-b border-gray-200 bg-linear-to-r from-gray-50 to-white px-3 py-2"
	>
		<div class="text-xs font-semibold tracking-[0.18em] text-gray-500 uppercase">Mermaid</div>
		<div class="text-xs font-medium text-gray-500">Streaming code...</div>
	</div>
	<pre
		class="overflow-x-auto bg-gray-950 p-4 text-xs leading-6 whitespace-pre-wrap text-gray-100"><code
			>{source}</code
		></pre>
</div>
