<script lang="ts">
  import type { AssistantModelOptions } from '$lib/api';
  import { ImageOutline, StarSolid } from 'flowbite-svelte-icons';
  import DropdownBadge from './DropdownBadge.svelte';
  import DropdownOption from './DropdownOption.svelte';
  export let modelOptions: AssistantModelOptions[];
  export let modelNodes: { [key: string]: HTMLElement };
  export let selectedModel: string;
  export let updateSelectedModel: (model: string) => void;
  export let allowVisionUpload: boolean;
  export let smallNameText: boolean = false;
</script>

<div class="relative z-0">
  {#each modelOptions as { value, name, description, supports_vision, is_new, highlight }}
    <div bind:this={modelNodes[value]}>
      <DropdownOption
        {value}
        {name}
        subtitle={description}
        selectedValue={selectedModel}
        update={updateSelectedModel}
        {smallNameText}
      >
        {#if highlight}
          <DropdownBadge extraClasses="border-amber-400 from-amber-50 to-amber-100 text-amber-700"
            ><span slot="icon"><StarSolid size="sm" /></span><span slot="name">Recommended</span
            ></DropdownBadge
          >
        {/if}
        {#if is_new}
          <DropdownBadge extraClasses="border-green-400 from-green-100 to-green-200 text-green-800"
            ><span slot="name">New</span></DropdownBadge
          >
        {/if}
        {#if supports_vision && allowVisionUpload}
          <DropdownBadge extraClasses="border-gray-400 from-gray-100 to-gray-200 text-gray-800"
            ><span slot="icon"><ImageOutline size="sm" /></span><span slot="name"
              >Vision capabilities</span
            ></DropdownBadge
          >
        {/if}
      </DropdownOption>
    </div>
  {/each}
</div>
