<script lang="ts">
  import type {FileUploadInfo} from "$lib/api";
  import {FileSolid, ExclamationCircleOutline} from "flowbite-svelte-icons";
  import ProgressCircle from "./ProgressCircle.svelte";

  export let info: FileUploadInfo;

  const nameForMimeType = (type: string) => {
    switch (type) {
      case "image/jpeg":
      case "image/png":
      case "image/gif":
        return "Image";
      case "video/mp4":
      case "video/quicktime":
        return "Video";
      case "audio/mpeg":
      case "audio/ogg":
        return "Audio";
      case "application/pdf":
        return "PDF";
      case "application/zip":
        return "ZIP";
      case "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return "Word Doc";
      default:
        return type;
    }
  };

  $: progress = info.progress;
  $: type = nameForMimeType(info.file.type);
  $: name = info.file.name;
  $: state = info.state;

  // TODO - delete!
</script>

<div class="rounded-lg items-center border-[1px] border-solid border-gray-300 flex px-2">
  <div>
    {#if state === "pending"}
      <ProgressCircle progress={progress} />
    {:else if state === "success"}
      <FileSolid class="w-6 h-6 text-green-500" />
    {:else}
      <ExclamationCircleOutline class="w-6 h-6 text-red-500" />
    {/if}
  </div>
  <div class="flex flex-col p-2">
    <div class="text-xs text-gray-500 font-bold">{name}</div>
    <div class="text-xs text-gray-500">{type}</div>
  </div>
</div>
