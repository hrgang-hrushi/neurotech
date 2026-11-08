# IndustryInsights Specification

## Overview
- **Target file:** `src/components/IndustryInsights.tsx`
- **Screenshot:** `docs/design-references/card-industry-insights.png`
- **Interaction model:** Interactive publisher logos, click to read summary article, tooltip insights

## DOM Structure
- `div.bg-[#303030].border.border-white/10.rounded-2xl.p-5.flex.flex-col.justify-between.text-white`
  - Header:
    - Left: `div.flex.items-center.gap-1.5`
      - Sparkle/Star 4-point icon (white)
      - Title: `span.text-xs.font-medium.text-white/90` ("Industry Insights")
    - Right: `button.w-7.h-7.rounded-full.bg-[#3d3d3d].border.border-white/10.flex.items-center.justify-center.text-gray-300.hover:text-white` (ArrowUpRight icon)
  - Content Text:
    - `p.text-xs.leading-relaxed.text-gray-200.mt-3`
      - "CNBC data shows " + `strong.font-semibold.text-white` ("retail spending") + " increased 4.2% in January as holiday demand extended into early 2025."
  - Media Publisher Badges Row:
    - `div.flex.items-center.gap-2.5.mt-5.pt-2`
      - Bloomberg Badge: Circular black badge with clean white serif "B"
      - CNBC Badge: Circular badge with peacock logo / CNBC wordmark
      - MarketWatch Badge: Circular green badge `#10b981` with dark "MW"
      - Reuters/Partner Badge: Circular orange badge `#f97316` with burst icon
      - Financial Times Badge: Circular/square peach badge with dark "FT"
