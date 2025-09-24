<script lang="ts">
  import { Tooltip } from 'flowbite-svelte';

  export let version: number | null | undefined;
  export let extraClasses = '';
  export let title: string | null = null;

  const baseClasses =
    'inline-flex items-center rounded-full border px-2 py-0.5 text-[0.625rem] font-semibold uppercase tracking-wide leading-none';
  const nextGenClasses = 'bg-blue-100 text-blue-800 border-blue-200';
  const classicClasses = 'bg-gray-100 text-gray-700 border-gray-200';

  $: isNextGen = (version ?? 0) >= 3;
  $: label = isNextGen ? 'Next-Gen' : 'Classic';
  $: classes =
    `${baseClasses} ${isNextGen ? nextGenClasses : classicClasses} ${extraClasses}`.trim();
  $: tooltip =
    (title ?? isNextGen)
      ? 'This assistant is using the latest Next-Gen architecture'
      : 'This assistant is using the previous Classic architecture';
</script>

<span class={classes} aria-label={`${label} assistant`}>
  {label}
</span>
<Tooltip class="font-light text-xs xl:text-sm" arrow={false}>{tooltip}</Tooltip>
