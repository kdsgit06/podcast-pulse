module.exports = {
  content: [
    "./src/**/*.{js,jsx,ts,tsx}",
    "../frontend/**/*.{js,jsx,ts,tsx,html}"
  ],
  theme: {
    extend: {
      colors: {
        'pulse-bg': '#f8f1e9',
        'pulse-border': '#e5e7eb',
        'pulse-blue': '#3b82f6',
        'pulse-gray': '#4b5563',
      },
      animation: {
        'pulse': 'pulse 1.5s infinite ease-in-out',
      },
      keyframes: {
        pulse: {
          '0%': { transform: 'scale(1)' },
          '50%': { transform: 'scale(1.03)' },
          '100%': { transform: 'scale(1)' },
        },
      },
    },
  },
  plugins: [],
}