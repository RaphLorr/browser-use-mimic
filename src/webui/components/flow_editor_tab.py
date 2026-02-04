import asyncio
import json
import os
import tempfile
from typing import Any, Dict

import gradio as gr

from playwright.sync_api import sync_playwright, expect

from src.flow.step_editor import parse_playwright_script
from src.utils import llm_provider
from browser_use.llm.messages import SystemMessage, UserMessage
from src.webui.webui_manager import WebuiManager


def create_flow_editor_tab(webui_manager: WebuiManager):
    """
    Table-based flow editor for Playwright codegen scripts.
    """
    tab_components: dict[str, Any] = {}

    with gr.Column():
        gr.Markdown(
            """
            ### Flow Editor (Table)
            Load a Playwright codegen script, edit steps in a table, and run them directly.
            """
        )

        script_path = gr.Textbox(
            label="Source Script Path",
            value=os.getenv("DEMO_OUTPUT_PATH", "./tmp/demo/recording.py"),
            interactive=True,
        )
        browser_type = gr.Dropdown(
            label="Browser Type",
            choices=["chromium", "firefox", "webkit"],
            value="chromium",
            interactive=True,
        )
        headless = gr.Checkbox(
            label="Headless",
            value=False,
            interactive=True,
        )
        status = gr.Markdown(value="Ready.")
        steps_table = gr.Dataframe(
            headers=["enabled", "type", "content"],
            datatype=["bool", "str", "str"],
            row_count=5,
            col_count=3,
            interactive=True,
            label="Steps",
        )
        with gr.Row():
            load_btn = gr.Button("📥 Load Script")
            run_btn = gr.Button("▶️ Run Steps", variant="primary")

    tab_components.update(
        dict(
            script_path=script_path,
            browser_type=browser_type,
            headless=headless,
            steps_table=steps_table,
            status=status,
            load_btn=load_btn,
            run_btn=run_btn,
        )
    )
    webui_manager.add_components("flow_editor", tab_components)

    def load_script(values: Dict[gr.components.Component, Any]):
        path = values.get(script_path, "").strip()
        if not path or not os.path.exists(path):
            return {
                status: gr.update(value=f"❌ Script not found: {path}"),
            }
        steps = parse_playwright_script(path)
        table = [[s.enabled, "action", s.line] for s in steps]

        marker_path = path + ".llm.json"
        if os.path.exists(marker_path):
            with open(marker_path, "r", encoding="utf-8") as f:
                markers = json.load(f).get("steps", [])
            for marker in markers:
                if marker.get("type") == "llm":
                    table.append([True, "llm", marker.get("prompt", "")])
        return {
            steps_table: gr.update(value=table),
            status: gr.update(value=f"Loaded {len(steps)} steps."),
        }

    def run_steps(values: Dict[gr.components.Component, Any]):
        data = values.get(steps_table, [])

        def get_setting(key, default=None):
            comp = webui_manager.id_to_component.get(f"agent_settings.{key}")
            return values.get(comp, default) if comp else default

        llm_provider_name = get_setting("llm_provider", None)
        llm_model_name = get_setting("llm_model_name", None)
        llm_temperature = get_setting("llm_temperature", 0.6)
        llm_base_url = get_setting("llm_base_url") or None
        llm_api_key = get_setting("llm_api_key") or None

        variables: dict[str, str] = {}

        def substitute_vars(line: str) -> str:
            for k, v in variables.items():
                line = line.replace(f"{{{{{k}}}}}", v)
            return line

        async def run_llm_step(prompt: str, page):
            if not llm_provider_name or not llm_model_name:
                raise ValueError("LLM provider/model not set in Agent Settings.")
            llm = llm_provider.get_llm_model(
                provider=llm_provider_name,
                model_name=llm_model_name,
                temperature=llm_temperature,
                base_url=llm_base_url,
                api_key=llm_api_key,
            )
            url = page.url
            title = page.title()
            sys_msg = SystemMessage(
                content="You are a decision engine. Return ONLY a JSON object with keys and string values."
            )
            user_msg = UserMessage(
                content=f"Prompt: {prompt}\\nCurrent URL: {url}\\nTitle: {title}\\nReturn JSON object."
            )
            result = await llm.ainvoke([sys_msg, user_msg])
            payload = result.completion
            data = json.loads(payload)
            for k, v in data.items():
                variables[k] = str(v)

        with sync_playwright() as p:
            browser = getattr(p, values.get(browser_type, "chromium")).launch(
                headless=bool(values.get(headless, False))
            )
            context = browser.new_context()
            page = context.new_page()

            for row in data:
                if not row or len(row) < 3:
                    continue
                enabled, step_type, content = row[0], row[1], row[2]
                if not enabled:
                    continue
                if step_type == "llm":
                    asyncio.run(run_llm_step(str(content), page))
                    continue
                line = substitute_vars(str(content))
                if line.startswith("await "):
                    line = line.replace("await ", "", 1)
                try:
                    exec(line, {"page": page, "expect": expect})
                except Exception as exc:
                    context.close()
                    browser.close()
                    return {status: gr.update(value=f"❌ Step failed: {exc}")}   

            context.close()
            browser.close()
        return {status: gr.update(value="✅ Steps executed successfully.")}

    load_btn.click(fn=load_script, inputs=webui_manager.get_components(), outputs=[steps_table, status])
    run_btn.click(fn=run_steps, inputs=webui_manager.get_components(), outputs=[status])

    return
