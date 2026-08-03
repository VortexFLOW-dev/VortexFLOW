export default {
  plugins: {
    // Tailwind v4's PostCSS plugin (@tailwindcss/postcss) does its own vendor
    // prefixing via the Rust engine (@tailwindcss/oxide) — autoprefixer is
    // redundant on v4 and is removed as part of this bump.
    '@tailwindcss/postcss': {},
  },
}
