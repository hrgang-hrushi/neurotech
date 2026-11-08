# HeaderNav Specification

## Overview
- **Target file:** `src/components/HeaderNav.tsx`
- **Screenshot:** `docs/design-references/header.png`
- **Interaction model:** click-driven tab navigation, hover states, interactive modal triggers

## DOM Structure
- `header.flex.items-center.justify-between.w-full.py-2`
  - Left: Logo container `flex items-center gap-2.5`
    - Diamond icon: 2 rotated rounded rhombuses in `#2ee59d`
    - Text: `FinPoint` (font-semibold, text-lg, text-white tracking-tight)
  - Center: Nav Capsule `nav.bg-[#161618].border.border-white/5.rounded-full.p-1.flex.items-center.gap-1`
    - Tab 1: `Dashboard` (text-xs text-gray-400 hover:text-white px-3 py-1.5)
    - Tab 2: `Investment` (active pill: `bg-white text-black font-semibold rounded-full px-4 py-1.5 text-xs shadow-sm`)
    - Tab 3: `Card`
    - Tab 4: `Savings`
    - Tab 5: `Activity`
    - Tab 6: `Settings`
  - Right: Actions `flex items-center gap-2.5`
    - Search button: `w-9 h-9 rounded-full bg-[#161618] border border-white/5 flex items-center justify-center text-gray-300 hover:text-white`
    - Notification bell button: `w-9 h-9 rounded-full bg-[#161618] border border-white/5 flex items-center justify-center text-gray-300 relative`
      - Notification dot: `w-2 h-2 rounded-full bg-[#f43f5e] absolute top-2 right-2 border-2 border-[#161618]`
    - Avatar: `w-9 h-9 rounded-full overflow-hidden border border-white/10 ring-1 ring-white/5`

## Computed Styles
- Logo color: `#ffffff`
- Nav Capsule background: `#161618`
- Active tab background: `#ffffff`, text: `#000000`
- Inactive tab text: `#9ca3af`
- Buttons background: `#161618`, border: `#27272a`
