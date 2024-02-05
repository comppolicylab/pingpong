import {toast} from "@zerodevx/svelte-toast";

/**
 * Show an error message as a toast.
 */
export const sadToast = (message: string) => {
  toast.push(message, {
    duration: 5000,
    theme: {
      // Error color
      '--toastBackground': '#F87171',
      '--toastBarBackground': '#EF4444',
      '--toastColor': '#fff',
    },
  })
};

/**
 * Show a success message as a toast.
 */
export const happyToast = (message: string) => {
  toast.push(message, {
    duration: 2000,
    theme: {
      // Success color
      '--toastBackground': '#A7F3D0',
      '--toastBarBackground': '#22C55E',
      '--toastColor': '#000',
    },
  })
};
