<script lang="ts" context="module">
	export const mainTextClass =
		'text-3xl text-color-blue-dark-50 font-serif font-bold px-4 truncate text-left';
</script>

<header
	class="items-center justify-between bg-blue-light-50 p-2 pt-6 pb-6 sm:flex sm:pb-2 lg:p-8 lg:pt-10 lg:pb-4"
>
	<div class="w-full min-w-0 overflow-hidden sm:max-w-2/3">
		<slot name="left" />
	</div>
	<div class="mt-4 ml-2 shrink-0 sm:mt-0 sm:ml-0">
		<slot name="right" />
	</div>
</header>
