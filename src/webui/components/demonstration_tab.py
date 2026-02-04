import json
import os
import subprocess
from typing import Any, Dict

import gradio as gr

from src.webui.webui_manager import WebuiManager


def create_demonstration_tab(webui_manager: WebuiManager):
    """
    Playwright codegen demo recorder.
    """
    tab_components: dict[str, Any] = {}

    with gr.Column():
        gr.Markdown(
            """
            ### Demonstration Mode (Playwright codegen)
            Record your own actions and export a runnable script.

            - This launches `npx playwright codegen` locally.
            - It will open a real browser window for you to operate.
            """
        )

        demo_url = gr.Textbox(
            label="Start URL (optional)",
            placeholder="https://example.com",
            interactive=True,
        )
        output_path = gr.Textbox(
            label="Script Output Path",
            value=os.getenv("DEMO_OUTPUT_PATH", "./tmp/demo/recording.py"),
            interactive=True,
        )
        target = gr.Dropdown(
            label="Script Target",
            choices=["python", "javascript", "typescript"],
            value="python",
            interactive=True,
        )
        demo_status = gr.Markdown(value="Recorder is idle.")
        llm_prompt = gr.Textbox(
            label="LLM Step Prompt",
            placeholder="Describe the decision you want LLM to make at this point...",
            lines=2,
            interactive=True,
        )
        llm_status = gr.Markdown(value="No LLM steps added.")

        with gr.Row():
            start_btn = gr.Button("▶️ Start Recording", variant="primary")
            stop_btn = gr.Button("⏹️ Stop Recording", variant="secondary")
            add_llm_btn = gr.Button("➕ Insert LLM Step", variant="secondary")

    tab_components.update(
        dict(
            demo_url=demo_url,
            output_path=output_path,
        target=target,
        demo_status=demo_status,
        llm_prompt=llm_prompt,
        llm_status=llm_status,
        start_btn=start_btn,
        stop_btn=stop_btn,
        add_llm_btn=add_llm_btn,
    )
    )
    webui_manager.add_components("demonstration", tab_components)

    def start_recording(start_url: str, out_path: str, tgt: str):
        if webui_manager.demo_process and webui_manager.demo_process.poll() is None:
            return {demo_status: gr.update(value="Recorder already running.")}

        url = (start_url or "").strip()
        out = (out_path or "").strip()
        tgt = tgt or "python"

        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        webui_manager.demo_markers = []

        cmd = ["npx", "-y", "playwright", "codegen", "--target", tgt, "--output", out]
        if url:
            cmd.append(url)

        try:
            proc = subprocess.Popen(cmd)
            webui_manager.demo_process = proc
        except Exception as exc:
            return {demo_status: gr.update(value=f"Failed to start recorder: {exc}")}

        return {demo_status: gr.update(value=f"Recording... (PID {proc.pid}) Output: {out}")}

    def stop_recording():
        proc = webui_manager.demo_process
        if not proc or proc.poll() is not None:
            webui_manager.demo_process = None
            return {demo_status: gr.update(value="Recorder is not running.")}

        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        webui_manager.demo_process = None
        return {demo_status: gr.update(value="Recording stopped.")}

    def add_llm_step(prompt_text: str, out_path: str):
        prompt = (prompt_text or "").strip()
        out = (out_path or "").strip()
        if not prompt:
            return {llm_status: gr.update(value="Please enter a prompt for the LLM step.")}
        if not out:
            return {llm_status: gr.update(value="Please set the Script Output Path first.")}

        marker = {"type": "llm", "prompt": prompt}
        webui_manager.demo_markers.append(marker)

        marker_path = out + ".llm.json"
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(marker_path, "w", encoding="utf-8") as f:
            json.dump({"steps": webui_manager.demo_markers}, f, ensure_ascii=False, indent=2)

        return {llm_status: gr.update(value=f"Added LLM step. Total: {len(webui_manager.demo_markers)}")}

    start_btn.click(
        fn=start_recording,
        inputs=[demo_url, output_path, target],
        outputs=[demo_status],
    )
    stop_btn.click(
        fn=stop_recording,
        inputs=None,
        outputs=[demo_status],
    )
    add_llm_btn.click(
        fn=add_llm_step,
        inputs=[llm_prompt, output_path],
        outputs=[llm_status],
    )

    return
