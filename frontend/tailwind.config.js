/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#071426',
        panel: '#0B2240',
        panel2: '#102A52',
        line: '#1E3A66',
        accent: '#FF6A00',
        accent2: '#FF8C1A',
        bodytext: '#C7D6EA',
      },
    },
  },
  plugins: [],
}
