import { describe, it, expect } from "bun:test";
import fs from "fs";
import path from "path";

describe("Design System Guard Tests (§12, §3.1, §6, §7)", () => {
  const tokensPath = path.resolve(__dirname, "../src/styles/ds-tokens.css");
  const componentsCssPath = path.resolve(__dirname, "../src/styles/ds-components.css");
  const componentsDir = path.resolve(__dirname, "../src/components");

  it("ds-tokens.css exists and defines core tokens (§12)", () => {
    expect(fs.existsSync(tokensPath)).toBe(true);
    const css = fs.readFileSync(tokensPath, "utf-8");

    // Check essential surface tokens
    expect(css).toContain("--ds-bg:");
    expect(css).toContain("--ds-surface:");
    expect(css).toContain("--ds-border:");
    expect(css).toContain("--ds-text-primary:");

    // Check sizing tokens (§6.1, §6.2)
    expect(css).toContain("--ds-header-height: 64px");
    expect(css).toContain("--ds-circle-size: 40px");
    expect(css).toContain("--ds-pill-height: 40px");

    // Check stage dot tokens (§4.3)
    expect(css).toContain("--ds-status-success:");
    expect(css).toContain("--ds-blue-tint-bg:");
  });

  it("ds-components.css exists and provides required classes (§6, §7)", () => {
    expect(fs.existsSync(componentsCssPath)).toBe(true);
    const css = fs.readFileSync(componentsCssPath, "utf-8");

    // §6.1, §6.2
    expect(css).toContain(".ds-topbar");
    expect(css).toContain(".ds-circle");
    expect(css).toContain(".ds-pill");
    expect(css).toContain(".ds-avatar-blue");

    // §7.1, §7.2, §7.5
    expect(css).toContain(".ds-card");
    expect(css).toContain(".ds-btn-primary");
    expect(css).toContain(".ds-btn-secondary");
    expect(css).toContain(".ds-btn-next-step");
    expect(css).toContain(".ds-stage-dot");
  });

  it("no heavy font weights (> 600) used across tokens or component styles", () => {
    const css = fs.readFileSync(tokensPath, "utf-8");
    expect(css).not.toContain("font-weight: 700");
    expect(css).not.toContain("font-weight: 800");
    expect(css).not.toContain("font-weight: 900");
  });

  it("screen components use design system tokens and avoid raw hardcoded background hexes", () => {
    const files = ["Navbar.tsx", "MessageStudio.tsx", "PhraseBoard.tsx", "EegMonitor.tsx"];

    for (const file of files) {
      const filePath = path.join(componentsDir, file);
      const content = fs.readFileSync(filePath, "utf-8");

      // Verify no hardcoded raw hex colors in className (e.g. bg-[#...], text-[#...])
      const rawHexMatches = content.match(/(bg|text|border)-\[#(?:[0-9a-fA-F]{3}){1,2}\]/g);
      expect(rawHexMatches).toBeNull();
    }
  });

  it("ds-tokens.css defines Author heading and subheading font tokens and chart tokens", () => {
    const css = fs.readFileSync(tokensPath, "utf-8");
    expect(css).toContain("--ds-font-heading:");
    expect(css).toContain("--ds-font-subheading:");
    expect(css).toContain("var(--font-author)");
    expect(css).toContain("--chart-line-primary:");
    expect(css).toContain("--chart-grid:");
  });

  it("LiveTelemetryChart uses @bklitui/ui/charts LiveLineChart on main dashboard", () => {
    const telemetryPath = path.join(componentsDir, "LiveTelemetryChart.tsx");
    expect(fs.existsSync(telemetryPath)).toBe(true);
    const content = fs.readFileSync(telemetryPath, "utf-8");
    expect(content).toContain("@bklitui/ui/charts");
    expect(content).toContain("<LiveLineChart");
    expect(content).toContain("<LiveLine");
    expect(content).toContain("<LiveXAxis");
    expect(content).toContain("<LiveYAxis");
    expect(content).toContain("<ChartTooltip");

    // Also verify MessageStudio embeds LiveTelemetryChart
    const studioContent = fs.readFileSync(path.join(componentsDir, "MessageStudio.tsx"), "utf-8");
    expect(studioContent).toContain("<LiveTelemetryChart");
  });

  it("ds-tokens.css defines #8FADE3 chart/progress blue and Watermelon UI pill buttons", () => {
    const css = fs.readFileSync(tokensPath, "utf-8");
    expect(css).toContain("#8FADE3");
    expect(css).toContain("--ds-chart-blue: #8FADE3");

    const compCss = fs.readFileSync(componentsCssPath, "utf-8");
    expect(compCss).toContain(".ds-btn-large-primary");
    expect(compCss).toContain(".ds-btn-outline");
    expect(compCss).toContain("border-radius: var(--ds-radius-full)");
  });

  it("enforces sm 8 (8px) unified rounding and eliminates badge wrappers around icons", () => {
    const css = fs.readFileSync(tokensPath, "utf-8");
    expect(css).toContain("--ds-radius-md: 8px");
    expect(css).toContain("--ds-radius-lg: 8px");
    expect(css).toContain("--ds-radius-xl: 8px");
    expect(css).toContain("--ds-radius-full: 8px");

    // Verify headers do not wrap icons in rounded-full badge containers
    const chartContent = fs.readFileSync(path.join(componentsDir, "LiveTelemetryChart.tsx"), "utf-8");
    expect(chartContent).not.toContain("w-9 h-9 rounded-full flex items-center justify-center bg-");

    const phraseContent = fs.readFileSync(path.join(componentsDir, "PhraseBoard.tsx"), "utf-8");
    expect(phraseContent).not.toContain("w-7 h-7 rounded-full flex items-center justify-center bg-");

    const eegContent = fs.readFileSync(path.join(componentsDir, "EegMonitor.tsx"), "utf-8");
    expect(eegContent).not.toContain("w-9 h-9 rounded-full flex items-center justify-center bg-");
  });
});
