# ProfitsOverview Specification

## Overview
- **Target file:** `src/components/ProfitsOverview.tsx`
- **Screenshot:** `docs/design-references/profits-and-cards.png`
- **Interaction model:** hover states on cards, interactive breakdown tooltips

## DOM Structure
- `div.flex.flex-col.gap-4.w-full`
  - Top Total Profits block:
    - Label: `span.text-xs.text-gray-400.font-normal` ("Total Profits")
    - Numbers row: `div.flex.items-center.gap-2.5.mt-1`
      - Value: `span.text-3xl.font-semibold.text-white.tracking-tight` ("$4,815.25")
      - Percentage badge: `span.flex.items-center.gap-1.bg-[#10b981]/15.text-[#34d399].border.border-[#10b981]/25.px-2.py-0.5.rounded-full.text-xs.font-semibold`
        - ArrowUpRight icon + "4.7%"
  - 2x2 Grid of Asset Breakdown Cards:
    - Card 1 (Stocks):
      - Indicator: `w-1 h-3 rounded-full bg-[#10b981]` + `span.text-xs.text-gray-400` ("Stocks")
      - Amount: `span.text-base.font-semibold.text-white` ("$4,815.25")
    - Card 2 (Bonds):
      - Indicator: `w-1 h-3 rounded-full bg-[#f97316]` + `span.text-xs.text-gray-400` ("Bonds")
      - Amount: `span.text-base.font-semibold.text-white` ("$2,145.15")
    - Card 3 (ETFs):
      - Indicator: `w-1 h-3 rounded-full bg-[#fb7185]` + `span.text-xs.text-gray-400` ("ETFs")
      - Amount: `span.text-base.font-semibold.text-white` ("$1,789.48")
    - Card 4 (REITs):
      - Indicator: `w-1 h-3 rounded-full bg-[#38bdf8]` + `span.text-xs.text-gray-400` ("REITs")
      - Amount: `span.text-base.font-semibold.text-white` ("$1,215.49")
