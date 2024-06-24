<script lang="ts">
    import { MultiSelect, type SelectOptionType } from "flowbite-svelte";
    import { type Writable } from 'svelte/store';
    
    export let name : string;

    export let items : SelectOptionType<string>[];

    export let value : Writable<string[]>;
    
    const addMoreFilesOption = { name: "+ Add more files", value: "add_more_files" };
        
    $: {
        if ($value.includes("add_more_files")) {
            console.log("Open file dialog"); // Open file dialog
            value.update(v => v.filter(item => item !== "add_more_files"));
        }
    }
</script>

<MultiSelect
    name={name}
    items={[addMoreFilesOption, ...items]}
    bind:value={$value}
/>