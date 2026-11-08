# FinPoint Interaction & Behavior Specification

## Interaction Model
The FinPoint dashboard is a high-density, interactive financial analytics control center with responsive states, hover effects, active pill toggles, and live animated charts.

### 1. Navigation Capsule Bar
- **Interaction Type:** Click-to-switch with smooth active capsule transition.
- **Tabs:** `Dashboard`, `Investment` (active by default), `Card`, `Savings`, `Activity`, `Settings`.
- **Active State:** White pill background (`#ffffff`), pure black bold text (`#000000`), subtle shadow.
- **Inactive State:** Text `#8e8e93`, hover to `#ffffff`, subtle dark background hover effect.

### 2. Action Controls
- **Search Button:** Circular dark button with magnifying glass; expands or opens interactive search modal on click.
- **Notifications Bell:** Circular dark button with red unread notification badge; shows alert dropdown on click.
- **Profile Avatar:** Circular avatar with subtle border; dropdown menu on click.
- **Filters Dropdown:** `Filters ∨` opens filter options (Date range, Asset category, Currency).
- **Refresh Button:** Rotating sync animation on click, updates metrics with a pulse effect.
- **Expand Button:** Fullscreen toggle or modal expansion.

### 3. Hero Portfolio Chart (Orange Card)
- **Timeframe Selector:** `1D`, `1W`, `1M`, `3M`, `1Y` (active with bottom underline), `All`.
- **Chart Line & Fill:**
  - Crisp glowing white path across 12 months (Jan - Dec).
  - Fine diagonal hatched pattern (`patternUnits="userSpaceOnUse"`) layered over smooth vertical gradient.
- **Active Marker Range (May - Aug):**
  - Highlighted vertical dashed markers at May and Aug with white anchor nodes.
  - Floating dark glass tooltip card:
    - `May 1`: `$58,200`
    - `+15.41%` green growth pill
    - `Aug 31`: `$62,940`
- **Hover/Interactive Crosshair:** Hovering along the curve shows an interactive cursor and dynamically calculates the interpolated value.

### 4. Watchlist Carousel
- **Items:** AAPL ($148.32, -0.92%), META ($337.17, -0.45%), AMZN ($172.58, +1.87%), MSFT ($382.30, +0.64%).
- **Interactive Sparklines:** Vector SVG paths with smooth curves, green for positive growth and red for negative.
- **Carousel Arrow:** Circular button on the right with hover state; advances to next batch of watchlist equities (e.g. GOOGL, NVDA, TSLA).

### 5. Allocation Performance
- **Asset Columns:**
  - Bonds: 45% filled with vermilion red (`#f03f16`).
  - Stocks: 85% filled with golden yellow (`#ffcf27`).
  - ETFs: 48% filled with clean white (`#ffffff`).
  - Crypto: Pattern track without filled bar.
- **Interactivity:** Hovering over bars displays detailed allocation amounts, dollar values, and rebalancing recommendations. Toggle between "Asset class" and percentage view.

### 6. Risk Score Gauge
- **Gauge Architecture:** Semicircular speedometer gauge with segmented tick markers.
- **Progress Arc:** Emerald-to-mint gradient fill (`#10b981` to `#34d399` to `#6ee7b7`) swept to 72/100, terminating in a glowing circular thumb indicator.
- **Hover/Click:** Reveals breakdown metrics (Volatility: Low, Sharpe Ratio: 1.82, Beta: 0.94).

### 7. Industry Insights
- **Card Background:** Medium elevated charcoal `#303030` with border `#404040`.
- **Publisher Logos:** Bloomberg (B), CNBC, MarketWatch (MW), Reuters/Orange Burst, Financial Times (FT). Hovering scales up the logo with an interactive news drawer.
