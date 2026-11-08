# AllocationPerformance Specification

## Overview
- **Target file:** `src/components/AllocationPerformance.tsx`
- **Screenshot:** `docs/design-references/card-allocation.png`
- **Interaction model:** Asset category dropdown filter, chart view switcher, hover tooltip on allocation bars

## DOM Structure
- `div.bg-[#141315].border.border-white/5.rounded-2xl.p-5.flex.flex-col.justify-between`
  - Header:
    - Title: `h3.text-sm.font-medium.text-white/90` ("Allocation Performance")
    - Right Controls:
      - Dropdown pill: `button.bg-[#1d1b1f].border.border-white/5.px-2.5.py-1.rounded-full.text-xs.text-gray-300.flex.items-center.gap-1` ("Asset class" + ChevronDown)
      - Bar icon button: `button.w-7.h-7.rounded-lg.bg-[#1d1b1f].border.border-white/5.flex.items-center.justify-center.text-gray-300` (BarChart2 icon)
  - Columns Container: `grid.grid-cols-4.gap-2.5.h-44.items-end`
    - Col 1 (Bonds):
      - Track with diagonal stripes (`repeating-linear-gradient(45deg, rgba(255,255,255,0.05) ...)` )
      - Bar: `h-[45%].bg-[#f03f16].rounded-xl.flex.items-start.justify-center.pt-2`
        - Text: `span.text-xs.font-bold.text-white` ("45%")
      - Label at bottom: `span.text-xs.text-gray-400.text-center` ("Bonds")
    - Col 2 (Stocks):
      - Track with diagonal stripes
      - Bar: `h-[85%].bg-[#ffcf27].rounded-xl.flex.items-start.justify-center.pt-2`
        - Text: `span.text-xs.font-bold.text-black` ("85%")
      - Label at bottom: `span.text-xs.text-gray-400.text-center` ("Stocks")
    - Col 3 (ETFs):
      - Track with diagonal stripes
      - Bar: `h-[48%].bg-white.rounded-xl.flex.items-start.justify-center.pt-2`
        - Text: `span.text-xs.font-bold.text-black` ("48%")
      - Label at bottom: `span.text-xs.text-gray-400.text-center` ("ETFs")
    - Col 4 (Crypto):
      - Empty track filled completely with diagonal stripes
      - Label at bottom: `span.text-xs.text-gray-400.text-center` ("Crypto")
