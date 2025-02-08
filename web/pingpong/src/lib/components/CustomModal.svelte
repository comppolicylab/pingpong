<script lang="ts">
    export let isOpen: boolean;
    export let onClose: () => void;

    const handleClose = (e: MouseEvent) => {
      if ((e.target as HTMLElement).id === "modal-overlay") {
        onClose();
      }
    };
  </script>

  {#if isOpen}
    <div
      id="modal-overlay"
      class="fixed inset-0 flex items-center justify-center bg-black/50 transition-opacity duration-300"
      on:click={handleClose}
    >
      <div
        class="bg-white w-3/4 h-3/4 p-6 rounded-2xl shadow-lg transition-transform duration-300 scale-100"
      >
        <button
          class="absolute top-4 right-4 text-gray-500 hover:text-gray-700"
          on:click={onClose}
        >
          ✕
        </button>
        <slot />
      </div>
    </div>
  {/if}
