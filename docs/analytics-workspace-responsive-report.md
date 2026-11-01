# Analytics Workspace responsive refinement

## Scope and design

The UI keeps the existing Analytics API, OpenCode session, Databricks provider, SQL routing, DuckDB behavior, materialization flow, and mock isolation. This change adjusts presentation and interaction only.

- **Typography:** shared rem tokens set labels at 12px, body and controls at 14px, SQL at 15px, and page titles at 24px on standard displays. The root grows to 17px at QHD and 19px at 4K. The old 6–10px text declarations now use the shared type tokens.
- **Layout:** the standard three-column grid uses a flexible center and resizable side panels. At Full HD the default Catalog and Ask Anvil panels are about 280px and 359px; at QHD about 323px and 391px; at 4K about 371px and 456px. Reading pages have a centered maximum width of about 1600–1710px, while SQL and results retain the wider work surface. The 1200px, 980px and 700px rules adapt the layout without a global transform or CSS zoom.
- **Header and health:** the header presents product, derived environment, and user. Catalog freshness and local storage moved to the system details panel in the footer. The default footer shows a readable health summary and catalog count; active operations appear only while running. The details panel retains Analytics, OpenCode, Databricks and DuckDB states.
- **Home:** recent tables, queries and analysis share *Continue working*. Pinned, Local data and Active operations appear only when they contain items. Permanent readiness cards and empty cards were removed.
- **Catalog:** All, Favorites and Local filters replace the duplicated Favorites/Recent navigation blocks. Object rows have SVG icons, names, optional local state and a star action. Recents remain on Home. Search works with each filter; starring an object keeps the expanded tree open.
- **Table Overview:** one concise summary presents type, format, columns, owner, modification time and local state. Remote-only objects omit empty local row and size metrics. Snapshot details remain on the Local data tab. Description and partitioning use a bounded reading width.
- **Ask Anvil:** the panel and text scale with the viewport. Context shows the current object or query with one useful detail; technical route details remain in the context tooltip. Two context actions remain visible. Deep investigation stays available under Options. Generic suggestions disappear once a table or query supplies context.
- **Accessibility:** buttons and tabs have larger targets, focus outlines also cover disclosure summaries, stars expose pressed state, the health summary is keyboard accessible, and state text accompanies color.

## White square root cause

The Catalog rendered a native `<button class="tree-star">` for every object, but the stylesheet had no `.tree-star` rule. Firefox displayed the browser's default light button background as a white square. Catalog stars now have an explicit transparent button style and inline SVG icons using `currentColor`; unknown object types use the table icon fallback. The visual check asserts that expanded Catalog rows contain SVG icons, contain no `<img>` placeholders, and have transparent star backgrounds.

## Verification

`make test` passed, including 70 Analytics offline tests and the lifecycle regressions. `python3 scripts/analytics_ui_visual_check.py` passed all four core views at exact 1366×768, 1920×1080, 2560×1440 and 3840×2160 viewports. It checks minimum text and panel sizes, global overflow, remote-only summaries, SQL result rows, Ask Anvil context, hidden Home sections, Catalog filters and favorites, icon rendering, Local data details, health disclosure, active operations, collapsible panels and workspace tab overflow.

Firefox was also checked at effective 125% and 150% device scale on 1366×768 and 1920×1080 windows. This exercises the smaller CSS viewport and physically larger text/control rendering; it is an automated proxy for browser zoom, not a manual check of Firefox's site zoom control. The checks use the static mock only and make no live Databricks, OpenCode or model request.

The [baseline screenshots](../artifacts/analytics-responsive/baseline/) preserve the previous Home at four sizes. The [final screenshots](../artifacts/analytics-responsive/final/) contain the 16 required view/viewport combinations, plus Catalog, health details and scaling captures. Key review images: [Home Full HD](../artifacts/analytics-responsive/final/home-1920x1080.png), [Home 4K](../artifacts/analytics-responsive/final/home-3840x2160.png), [Table Full HD](../artifacts/analytics-responsive/final/table-remote-1920x1080.png), [Table 4K](../artifacts/analytics-responsive/final/table-remote-3840x2160.png), [Query Full HD](../artifacts/analytics-responsive/final/query-results-1920x1080.png), [Query 4K](../artifacts/analytics-responsive/final/query-results-3840x2160.png).
