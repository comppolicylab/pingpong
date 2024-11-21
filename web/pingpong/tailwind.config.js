/** @type {import('tailwindcss').Config}*/
const config = {
  content: [
    './src/**/*.{html,js,svelte,ts}',
    './node_modules/flowbite-svelte/**/*.{html,js,svelte,ts}'
  ],

  darkMode: 'class',

  theme: {
    container: {
      center: true,
      padding: '2rem'
    },
    fontFamily: {
      sans: ['Inter', 'sans-serif'],
      serif: ['STIX Two Text', 'serif'],
      mono: ['Fira Code', 'monospace']
    },
    extend: {
      borderRadius: {
        '4xl': '2rem'
      },
      borderWidth: {
        3: '3px'
      },
      colors: {
        'blue-dark-50': '#201E45',
        'blue-dark-40': '#2D2A62',
        'blue-dark-30': '#545193',
        'blue-light-50': '#F1F4FF',
        'blue-light-40': '#D9E2FF',
        'blue-light-30': '#C2D0FF',
        'red-light-40': '#f1e3e3',
        'red-light-50': '#f8f2f2',
        'red-light-30': '#E4C9C9',
        'brown-dark': '#3d3929',
        seasalt: '#f8f9fa',
        melon: '#FEB8AF',
        'coral-pink': '#FD9486',
        orange: '#FC624D',
        'orange-dark': '#E33F0C',
        'orange-light': '#FFF7F1',
        gold: '#FFD076',
        'gold-light': '#FFF6E4',
        'red-pink-50': '#fef2f3',
        'red-pink-100': '#fde6e7',
        'red-pink-400': '#f27a8a',
        'red-pink-800': '#b31d3f',
        'pastel-green-50': '#f0fdf4',
        'pastel-green-100': '#dcfce7',
        'pastel-green-400': '#48e082',
        'pastel-green-800': '#156635',
        'electric-violet-50': '#f4f3ff',
        'electric-violet-100': '#ebe9fe',
        'electric-violet-400': '#9e8cf9',
        'electric-violet-800': '#4d23b4',
        'copper-rust-50': '#fbf6f5',
        'copper-rust-100': '#f7eeec',
        'copper-rust-400': '#d0a29c',
        'copper-rust-800': '#733e3e',
        'lightning-yellow-50': '#fffeea',
        'lightning-yellow-100': '#fffbc5',
        'lightning-yellow-400': '#ffe01c',
        'lightning-yellow-800': '#975109',
        'red-purple-50': '#fbf4f8',
        'red-purple-100': '#f8ebf1',
        'red-purple-400': '#d98db2',
        'red-purple-800': '#81334f',
        'shakespeare-blue-50': '#ecfdff',
        'shakespeare-blue-100': '#d0f7fd',
        'shakespeare-blue-400': '#26c9ea',
        'shakespeare-blue-800': '#175a73',
        'monza-red-50': '#fff0f1',
        'monza-red-100': '#ffdee1',
        'monza-red-400': '#ff5e6e',
        'monza-red-800': '#ab0919',
        'salem-green-50': '#effef5',
        'salem-green-100': '#dafee8',
        'salem-green-400': '#41e787',
        'salem-green-800': '#116a38',
        'chalet-green-50': '#f2f6ef',
        'chalet-green-100': '#e3eadd',
        'chalet-green-400': '#88a576',
        'chalet-green-800': '#36452f',
        'royal-blue-50': '#e7f2ff',
        'royal-blue-100': '#d4e7ff',
        'royal-blue-400': '#5284ff',
        'royal-blue-800': '#031bd8',
        'sunset-orange-50': '#fdf9e9',
        'sunset-orange-100': '#fbf1c6',
        'sunset-orange-400': '#efae20',
        'sunset-orange-800': '#7f4014',
        'opal-50': '#f3f8f8',
        'opal-100': '#e1ecea',
        'opal-400': '#729e98',
        'opal-800': '#3b4f4f'
      }
    }
  },

  // eslint-disable-next-line @typescript-eslint/no-require-imports
  plugins: [require('flowbite/plugin')]
};

module.exports = config;
