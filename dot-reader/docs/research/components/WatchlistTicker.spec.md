# WatchlistTicker Specification

## Overview
- **Target file:** `src/components/WatchlistTicker.tsx`
- **Screenshot:** `docs/design-references/watchlist-row.png`
- **Interaction model:** Interactive ticker items with hover sparkline glow, carousel right button `>` to slide or cycle tickers.

## DOM Structure
- `div.w-full.bg-[#141315].border.border-white/5.rounded-2xl.px-5.py-3.flex.items-center.justify-between.gap-4`
  - Left Label: `span.text-xs.font-medium.text-gray-400.shrink-0` ("Watchlist")
  - Ticker Grid / Items (4 items):
    - Item 1: AAPL
      - White circular badge with Apple logo (black)
      - Symbol: "AAPL" (text-xs text-gray-400)
      - Price & Change: "$148.32" (text-sm font-semibold text-white) + " -0.92%" (text-xs text-red-400)
      - Red vector sparkline curve
    - Item 2: META
      - Blue circular badge with Meta infinity logo (white)
      - Symbol: "META" (text-xs text-gray-400)
      - Price & Change: "$337.17" (text-sm font-semibold text-white) + " -0.45%" (text-xs text-red-400)
      - Red vector sparkline curve
    - Item 3: AMZN
      - White circular badge with Amazon 'a' logo (black)
      - Symbol: "AMZN" (text-xs text-gray-400)
      - Price & Change: "$172.58" (text-sm font-semibold text-white) + " +1.87%" (text-xs text-emerald-400)
      - Green vector sparkline curve
    - Item 4: MSFT
      - White circular badge with Microsoft 4-square colored logo (Red, Green, Blue, Yellow)
      - Symbol: "MSFT" (text-xs text-gray-400)
      - Price & Change: "$382.30" (text-sm font-semibold text-white) + " +0.64%" (text-xs text-emerald-400)
      - Green vector sparkline curve
  - Right: Carousel Arrow `button.w-8.h-8.rounded-full.bg-[#201e22].border.border-white/5.flex.items-center.justify-center.text-gray-400.hover:text-white`
    - ChevronRight icon
