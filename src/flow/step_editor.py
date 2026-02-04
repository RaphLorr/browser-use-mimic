from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass
class FlowStep:
    enabled: bool
    line: str


def parse_playwright_script(script_path: str) -> list[FlowStep]:
    steps: list[FlowStep] = []
    with open(script_path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("page.") or line.startswith("await page."):
                steps.append(FlowStep(enabled=True, line=line))
            elif line.startswith("expect("):
                steps.append(FlowStep(enabled=True, line=line))
    return steps


def steps_to_script(
    steps: Iterable[FlowStep],
    browser_type: str = "chromium",
    headless: bool = False,
) -> str:
    lines: list[str] = []
    lines.append("from playwright.sync_api import sync_playwright\n\n")
    lines.append("def run(playwright):\n")
    lines.append(f"    browser = playwright.{browser_type}.launch(headless={str(headless)})\n")
    lines.append("    context = browser.new_context()\n")
    lines.append("    page = context.new_page()\n\n")
    for step in steps:
        if not step.enabled:
            continue
        lines.append(f"    {step.line}\n")
    lines.append("\n    context.close()\n")
    lines.append("    browser.close()\n\n")
    lines.append("with sync_playwright() as playwright:\n")
    lines.append("    run(playwright)\n")
    return "".join(lines)
