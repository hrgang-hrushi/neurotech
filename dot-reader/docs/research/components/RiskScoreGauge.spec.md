# RiskScoreGauge Specification

## Overview
- **Target file:** `src/components/RiskScoreGauge.tsx`
- **Screenshot:** `docs/design-references/card-risk-score.png`
- **Interaction model:** Interactive gauge hover, click to see historical volatility and Sharpe ratio

## DOM Structure
- `div.bg-[#141315].border.border-white/5.rounded-2xl.p-5.flex.flex-col.justify-between.relative`
  - Header:
    - Left: `span.text-xs.font-medium.text-gray-400` ("Risk Score")
    - Right: `button.w-7.h-7.rounded-full.bg-[#1d1b1f].border.border-white/5.flex.items-center.justify-center.text-gray-400.hover:text-white` (ArrowUpRight icon)
  - Score Display:
    - `div.flex.items-baseline.gap-1`
      - Score: `span.text-3xl.font-bold.text-white` ("72")
      - Max: `span.text-sm.text-gray-400` ("/100")
  - Speedometer Gauge:
    - Semicircular SVG arch with radius ~90
    - Background track: segmented ticks and dark curved track
    - Progress arc: mint-to-emerald gradient (`#22c55e` to `#34d399` to `#a7f3d0`) with stroke-linecap="round"
    - Circular glowing indicator thumb positioned at 72% of the arc with drop-shadow glow
  - Bottom Caption:
    - `p.text-xs.text-gray-400.text-center.mt-1` ("Stability improved by +4%")
