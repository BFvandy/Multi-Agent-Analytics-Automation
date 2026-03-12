"""
Visualization tool — generates a PowerPoint slide by calling generate_slide.js.
The agent populates a structured JSON payload which is passed to the JS slide builder.
"""

import os
import json
import subprocess
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR   = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR.parent / "output"
JS_SCRIPT  = BASE_DIR / "generate_slide.js"


def generate_slide(
    title: str,
    subtitle: str,
    bullets: list,
    chart_title: str,
    chart_data: list,
    table_title: str,
    table_data: list,
    footnote: str,
    output_filename: str = "analytics_output.pptx",
) -> str:
    """
    Generate a professional PowerPoint slide with chart and data table.

    Args:
        title:           Headline sentence summarizing the key finding
        subtitle:        Month and reference date context line
        bullets:         List of 3-5 key insight strings
        chart_title:     Title for the bar chart
        chart_data:      List of dicts: [{"label": "Signature", "value": 15.1, "ctg": 3.51}, ...]
        table_title:     Title for the data table
        table_data:      2D list — first row is headers, rest are data rows
        footnote:        Small explanatory text below the table
        output_filename: Name of the output .pptx file

    Returns:
        JSON string with status and output file path
    """
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = str(OUTPUT_DIR / output_filename)

        slide_data = {
            "title":        title,
            "subtitle":     subtitle,
            "bullets":      bullets,
            "chartTitle":   chart_title,
            "chartData":    chart_data,
            "tableTitle":   table_title,
            "tableData":    table_data,
            "footnote":     footnote,
            "outputPath":   output_path,
        }

        # Write payload to temp file for JS to read
        payload_path = BASE_DIR / "_slide_payload.json"
        with open(payload_path, "w") as f:
            json.dump(slide_data, f, indent=2)

        # Call generate_slide.js
        result = subprocess.run(
            ["node", str(JS_SCRIPT), str(payload_path)],
            capture_output=True, text=True, timeout=30
        )

        # Clean up temp file
        payload_path.unlink(missing_ok=True)

        if result.returncode != 0:
            return json.dumps({
                "status": "error",
                "error":  result.stderr or result.stdout,
            })

        return json.dumps({
            "status":      "success",
            "output_path": output_path,
            "message":     f"Slide saved to {output_path}",
        })

    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})
