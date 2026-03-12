/**
 * Executive Analytics Slide Generator
 * Accepts a JSON payload file path as argument: node generate_slide.js payload.json
 * Color scheme: Midnight Executive — navy + ice blue + white
 */

const pptxgen = require("pptxgenjs");
const fs = require("fs");

// ── Load payload ──────────────────────────────────────────────
const payloadPath = process.argv[2];
if (!payloadPath) {
  console.error("Usage: node generate_slide.js <payload.json>");
  process.exit(1);
}

const data = JSON.parse(fs.readFileSync(payloadPath, "utf8"));

// ── Color Palette ─────────────────────────────────────────────
const C = {
  navy:     "1E2761",
  iceBlue:  "CADCFC",
  blue:     "2D62C7",
  white:    "FFFFFF",
  offWhite: "F5F7FA",
  darkText: "1A1A2E",
  mutedText:"64748B",
  accent:   "E8322A",
  positive: "1A7D4A",
  divider:  "CADCFC",
};

async function buildSlide(data) {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_WIDE"; // 13.3" × 7.5"

  const slide = pres.addSlide();
  slide.background = { color: C.offWhite };

  const W = 13.3, H = 7.5;
  const MARGIN = 0.3;
  const HEADER_H = 1.05;
  const LEFT_W = 4.4;
  const RIGHT_X = LEFT_W + MARGIN * 2 + 0.1;
  const RIGHT_W = W - RIGHT_X - MARGIN;
  const CONTENT_Y = HEADER_H + 0.2;
  const CONTENT_H = H - CONTENT_Y - MARGIN;

  // ── Header bar ───────────────────────────────────────────────
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: W, h: HEADER_H,
    fill: { color: C.navy }, line: { color: C.navy },
  });

  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 0.06, h: HEADER_H,
    fill: { color: C.iceBlue }, line: { color: C.iceBlue },
  });

  slide.addText(data.title, {
    x: 0.2, y: 0.04, w: W - 0.4, h: 0.65,
    fontSize: 17, bold: true, color: C.white,
    fontFace: "Calibri", valign: "middle", margin: 0,
  });

  slide.addText(data.subtitle, {
    x: 0.2, y: 0.72, w: W - 0.4, h: 0.28,
    fontSize: 10, color: C.iceBlue,
    fontFace: "Calibri", valign: "top", margin: 0,
  });

  // ── Left column ───────────────────────────────────────────────
  slide.addShape(pres.shapes.RECTANGLE, {
    x: MARGIN * 0.5, y: CONTENT_Y, w: LEFT_W, h: CONTENT_H,
    fill: { color: C.white },
    shadow: { type: "outer", color: "000000", blur: 6, offset: 2, angle: 135, opacity: 0.08 },
    line: { color: "E2E8F0", width: 0.5 },
  });

  slide.addShape(pres.shapes.RECTANGLE, {
    x: MARGIN * 0.5, y: CONTENT_Y, w: 0.06, h: CONTENT_H,
    fill: { color: C.blue }, line: { color: C.blue },
  });

  slide.addText("KEY INSIGHTS", {
    x: MARGIN * 0.5 + 0.15, y: CONTENT_Y + 0.12, w: LEFT_W - 0.2, h: 0.3,
    fontSize: 9, bold: true, color: C.navy,
    fontFace: "Calibri", charSpacing: 2, margin: 0,
  });

  slide.addShape(pres.shapes.LINE, {
    x: MARGIN * 0.5 + 0.15, y: CONTENT_Y + 0.45,
    w: LEFT_W - 0.3, h: 0,
    line: { color: C.divider, width: 1 },
  });

  const bulletItems = (data.bullets || []).map((b, i) => ({
    text: b,
    options: {
      bullet: true,
      breakLine: i < data.bullets.length - 1,
      paraSpaceAfter: 8,
    },
  }));

  slide.addText(bulletItems, {
    x: MARGIN * 0.5 + 0.15, y: CONTENT_Y + 0.55,
    w: LEFT_W - 0.25, h: CONTENT_H - 0.65,
    fontSize: 11, color: C.darkText,
    fontFace: "Calibri", valign: "top", margin: 0,
  });

  // ── Right column ──────────────────────────────────────────────
  const CHART_H = 2.55;
  const TABLE_Y = CONTENT_Y + CHART_H + 0.2;
  const TABLE_H = 1.65;
  const FOOTNOTE_Y = TABLE_Y + TABLE_H + 0.08;

  slide.addText(data.chartTitle, {
    x: RIGHT_X, y: CONTENT_Y + 0.05, w: RIGHT_W, h: 0.28,
    fontSize: 10, bold: true, color: C.navy,
    fontFace: "Calibri", margin: 0,
  });

  const chartColors = (data.chartData || []).map(d => d.value >= 0 ? C.blue : C.accent);
  slide.addChart(pres.charts.BAR, [
    {
      name: "YoY %",
      labels: data.chartData.map(d => d.label),
      values: data.chartData.map(d => d.value),
    }
  ], {
    x: RIGHT_X, y: CONTENT_Y + 0.32,
    w: RIGHT_W, h: CHART_H - 0.35,
    barDir: "col",
    chartColors,
    chartArea: { fill: { color: C.white }, roundedCorners: false },
    catAxisLabelColor: C.mutedText,
    valAxisLabelColor: C.mutedText,
    valGridLine: { color: "E2E8F0", size: 0.5 },
    catGridLine: { style: "none" },
    showValue: true,
    dataLabelColor: C.darkText,
    dataLabelFontSize: 9,
    dataLabelFormatCode: '0.00"%"',
    showLegend: false,
    valAxisNumFmt: '0.00"%"',
  });

  // ── Table ─────────────────────────────────────────────────────
  slide.addText(data.tableTitle, {
    x: RIGHT_X, y: TABLE_Y, w: RIGHT_W, h: 0.22,
    fontSize: 10, bold: true, color: C.navy,
    fontFace: "Calibri", margin: 0,
  });

  const [headerRow, ...bodyRows] = data.tableData || [[]];
  const numCols = headerRow.length;
  const colW = Array(numCols).fill(RIGHT_W / numCols);

  const tableRows = [
    headerRow.map(cell => ({
      text: String(cell),
      options: {
        bold: true, color: C.white,
        fill: { color: C.navy },
        fontSize: 9, align: "center",
      },
    })),
    ...bodyRows.map((row, ri) =>
      row.map((cell, ci) => {
        const isLast = ri === bodyRows.length - 1;
        const cellStr = String(cell);
        const isNeg = cellStr.startsWith("-");
        const isPos = (cellStr.startsWith("+")) && ci >= 3;
        return {
          text: cellStr,
          options: {
            fontSize: 9,
            color: isNeg ? C.accent : isPos ? C.positive : C.darkText,
            bold: isLast,
            fill: { color: isLast ? C.iceBlue : ri % 2 === 0 ? C.white : "F0F4FF" },
            align: ci === 0 ? "left" : "center",
          },
        };
      })
    ),
  ];

  slide.addTable(tableRows, {
    x: RIGHT_X, y: TABLE_Y + 0.25,
    w: RIGHT_W, h: TABLE_H - 0.25,
    colW,
    border: { pt: 0.5, color: "E2E8F0" },
    rowH: 0.26,
  });

  // ── Footnote ──────────────────────────────────────────────────
  if (data.footnote) {
    slide.addText(data.footnote, {
      x: RIGHT_X, y: FOOTNOTE_Y, w: RIGHT_W, h: 0.35,
      fontSize: 8, color: C.mutedText, italic: true,
      fontFace: "Calibri", valign: "top", margin: 0,
    });
  }

  const outputPath = data.outputPath || "analytics_output.pptx";
  await pres.writeFile({ fileName: outputPath });
  console.log(`Slide saved to: ${outputPath}`);
}

buildSlide(data).catch(err => {
  console.error("Error generating slide:", err);
  process.exit(1);
});
