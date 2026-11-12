// Copies third-party browser files into site/ so the page makes no requests to
// other origins (no CDNs, no Google Fonts). Run after upgrading these packages.
import { copyFileSync, mkdirSync } from "node:fs";

const files = [
  ["node_modules/chart.js/dist/chart.umd.min.js", "site/vendor/chart.umd.min.js"],
  ["node_modules/chartjs-adapter-date-fns/dist/chartjs-adapter-date-fns.bundle.min.js", "site/vendor/chartjs-adapter-date-fns.bundle.min.js"],
  ["node_modules/@fontsource-variable/inter/files/inter-latin-wght-normal.woff2", "site/fonts/inter-latin-wght-normal.woff2"],
  ["node_modules/@fontsource/instrument-serif/files/instrument-serif-latin-400-normal.woff2", "site/fonts/instrument-serif-latin-400-normal.woff2"],
  ["node_modules/@fontsource/instrument-serif/files/instrument-serif-latin-400-italic.woff2", "site/fonts/instrument-serif-latin-400-italic.woff2"],
];
mkdirSync("site/vendor", { recursive: true });
mkdirSync("site/fonts", { recursive: true });
for (const [from, to] of files) {
  copyFileSync(from, to);
  console.log(`${from} -> ${to}`);
}
