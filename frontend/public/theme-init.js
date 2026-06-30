// Set the initial theme before first paint to avoid a flash of the wrong theme.
// Kept as an external (same-origin) file rather than an inline <script> so the
// Content-Security-Policy can use a strict script-src 'self' without
// 'unsafe-inline'. Loaded synchronously in <head>.
try {
  if (localStorage.getItem('vf-theme') !== 'light') {
    document.documentElement.classList.add('dark')
  }
} catch (e) {
  document.documentElement.classList.add('dark')
}
