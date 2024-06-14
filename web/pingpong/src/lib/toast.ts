import { toast } from '@zerodevx/svelte-toast';

/**
 * Show an error message as a toast.
 */
export const sadToast = (message: string) => {
  toast.push(message, {
    duration: 5000,
    theme: {
      // Error color
      '--toastBackground': '#FFBA89',
      '--toastBarBackground': '#FF7043',
      '--toastColor': '#201E45',
      '--toastWidth': '20rem'
    }
  });
};

/**
 * Show a success message as a toast.
 */
export const happyToast = (message: string) => {
  toast.push(message, {
    duration: 2000,
    theme: {
      // Success color
      '--toastBackground': '#B4F9E9',
      '--toastBarBackground': '#61DCBA',
      '--toastColor': '#201E45',
      '--toastWidth': '20rem'
    }
  });
};
