# Third-party notices

Files under `site/vendor/` and `site/fonts/` are copied from npm packages by `npm run vendor` so the site makes no
requests to other origins.

| File | Project | License |
|---|---|---|
| `site/vendor/chart.umd.min.js` | [Chart.js](https://www.chartjs.org/) | MIT |
| `site/vendor/chartjs-adapter-date-fns.bundle.min.js` | [chartjs-adapter-date-fns](https://github.com/chartjs/chartjs-adapter-date-fns) (bundles [date-fns](https://date-fns.org/), MIT) | MIT |
| `site/fonts/inter-*.woff2` | [Inter](https://rsms.me/inter/) by Rasmus Andersson, via Fontsource | SIL Open Font License 1.1 |
| `site/fonts/instrument-serif-*.woff2` | [Instrument Serif](https://github.com/Instrument/instrument-serif) by Instrument, via Fontsource | SIL Open Font License 1.1 |

## Data

Prices come from FRED (Federal Reserve Bank of St. Louis), the U.S. Bureau of Labor Statistics, Yahoo Finance and
DRAMeXchange. Each source has its own terms. DRAMeXchange's Terms of Use (§6.2) forbid republishing its prices, which
is why collected data is kept out of the public source repository and the dashboard is private.
