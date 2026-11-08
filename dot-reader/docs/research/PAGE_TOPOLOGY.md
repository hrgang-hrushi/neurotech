# FinPoint Dashboard - Page Topology & Architecture

## Canvas & Bezel Frame
- Outer background: `#121214` (dark workstation canvas)
- Dashboard container: Sleek rounded slate frame (`rounded-[36px]` or `rounded-[32px]`), border `border-white/10`, inner dark background `#09090b`.
- Responsive padding: `p-6` to `p-8` desktop, `p-4` mobile.

## Visual Hierarchy & Grid Layout
```
+-----------------------------------------------------------------------------------------+
| [FinPoint Logo]     [Nav: Dashboard | (Investment) | Card | Savings | Activity | Settings]     [Search] [Bell] [Avatar] |
+-----------------------------------------------------------------------------------------+
| Portfolio assets Performance        [|||||| 76 Health Score]                 [Filters v] [Sync] [↗] |
+-----------------------------------------------------------------------------------------+
| LEFT COLUMN (approx 32%)                  | RIGHT COLUMN (approx 68% - HERO CARD)       |
| Total Profits: $4,815.25 [↗ 4.7%]         | Portfolio Value: $54,815.25 [↙ 2.4%]        |
|                                           | Timeframe: 1D  1W  1M  3M  (1Y)  All        |
| [ | Stocks   $4,815.25 ] [ | Bonds $2,145]| Interactive Spline Chart with hatching      |
| [ | ETFs     $1,789.48 ] [ | REITs $1,215]| Tooltip Range: May 1 ($58.2k) -> Aug 31 ($62.9k) |
+-----------------------------------------------------------------------------------------+
| Watchlist: [AAPL $148.32]  [META $337.17]  [AMZN $172.58]  [MSFT $382.30]           [ > ]|
+-----------------------------------------------------------------------------------------+
| BOTTOM ROW (3 CARDS)                                                                    |
| Card 1 (Allocation ~48%):                | Card 2 (Risk Score ~26%): | Card 3 (Insights ~26%): |
| Bonds 45% (Red)                          | Score: 72 / 100           | Star + Industry Insights|
| Stocks 85% (Yellow)                      | Speedometer Arc (Mint)    | Retail spending text    |
| ETFs 48% (White)                         | Stability improved +4%    | [B] [CNBC] [MW] [*] [FT]|
| Crypto (Pattern)                         |                           |                         |
+-----------------------------------------------------------------------------------------+
```

## Color Palette Tokens
- Background Base: `#080808` / `#0a0a0c`
- Card Dark Surface: `#141315` / `#161518`
- Card Border: `#222024`
- Hero Card Orange: `#f03f16` to `#eb4c24`
- Hero Card Hatch: fine diagonal line overlay (`rgba(255, 255, 255, 0.15)`)
- Accent Yellow: `#ffcf27`
- Accent Mint/Green: `#22c55e` / `#34d399`
- Accent Red/Pink: `#ef4444` / `#f43f5e`
- Insights Card Charcoal: `#303030`
- Text Primary: `#ffffff`
- Text Secondary: `#9ca3af` / `#8e8e93`
- Text Muted: `#52525b`
