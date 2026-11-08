# HeroPortfolioChart Specification

## Overview
- **Target file:** `src/components/HeroPortfolioChart.tsx`
- **Screenshot:** `docs/design-references/hero-chart-card.png`
- **Interaction model:** Timeframe toggle (1D, 1W, 1M, 3M, 1Y, All), interactive SVG chart hover crosshairs, custom SVG pattern hatching

## DOM Structure
- `div.relative.overflow-hidden.rounded-3xl.bg-gradient-to-br.from-[#ff411a].to-[#eb3b14].p-6.text-white.shadow-xl`
  - Top Row:
    - Left:
      - Label: `span.text-xs.font-medium.text-white/80` ("Portfolio Value")
      - Value row: `div.flex.items-center.gap-3.mt-1`
        - Value: `span.text-3xl.font-bold.text-white` ("$54,815.25")
        - Pill badge: `span.flex.items-center.gap-1.bg-white.text-black.px-2.5.py-0.5.rounded-full.text-xs.font-semibold.shadow-sm`
          - ArrowDownRight / ArrowDownLeft icon + "2.4%"
    - Right:
      - Timeframe selector: `div.flex.items-center.gap-3.text-xs.font-semibold`
        - `1D`, `1W`, `1M`, `3M`, `1Y` (active with bottom white underline), `All`
  - Chart Canvas:
    - Y-Axis markers: `$90K`, `$70K` aligned on the left
    - SVG spline chart:
      - Fine 45-degree diagonal hatched lines under the path (`pattern#hatch`)
      - Smooth glowing white path line
      - Active range: vertical dashed highlighted lines at May and Aug
      - Nodes on curve at May and Aug
    - Range Tooltip Box (between May and Aug):
      - Floating dark container `bg-[#0e0c0e]/90.backdrop-blur-md.border.border-white/10.rounded-xl.p-3.text-xs.shadow-2xl`
      - "May 1" ... "$58,200"
      - Badge: "+15.41%"
      - "Aug 31" ... "$62,940"
  - X-Axis Months:
    - `Jan`, `Feb`, `Mar`, `Apr`, `May`, `Jun`, `Jul`, `Aug`, `Sep`, `Oct`, `Nov`, `Dec`
