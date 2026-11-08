# PortfolioHeader Specification

## Overview
- **Target file:** `src/components/PortfolioHeader.tsx`
- **Screenshot:** `docs/design-references/portfolio-heading.png`
- **Interaction model:** click-driven filters, health score breakdown on hover, refresh animation on click

## DOM Structure
- `div.flex.items-center.justify-between.w-full.py-2`
  - Left: Title `h1.text-xl.font-normal.text-white/95.tracking-tight` ("Portfolio assets Performance")
  - Middle: Health Score Indicator `div.flex.items-center.gap-2.5.bg-[#1a191b].border.border-white/5.px-3.py-1.5.rounded-full`
    - Segmented bar graphic: 12 mini vertical bars (8 colored amber/yellow `#f59e0b`, 4 muted `#3f3f46`)
    - Score text: `span.font-semibold.text-sm.text-white` ("76")
    - Label text: `span.text-xs.text-gray-400` ("Health Score")
  - Right: Action buttons group `flex items-center gap-2`
    - Filter pill button: `bg-[#1a191b] border border-white/5 text-gray-300 px-3 py-1.5 rounded-full text-xs flex items-center gap-1.5 hover:text-white`
      - Text: "Filters" + ChevronDown icon
    - Refresh circular button: `w-8 h-8 rounded-full bg-[#1a191b] border border-white/5 text-gray-300 hover:text-white flex items-center justify-center`
      - RefreshCw / RotateCw icon (animates on click)
    - Expand circular button: `w-8 h-8 rounded-full bg-[#1a191b] border border-white/5 text-gray-300 hover:text-white flex items-center justify-center`
      - ArrowUpRight icon
