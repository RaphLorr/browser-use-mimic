import os
from typing import Any, Dict

import gradio as gr

from src.flow.hybrid_runner import run_hybrid_flow
from src.webui.webui_manager import WebuiManager


def create_hybrid_flow_tab(webui_manager: WebuiManager):
    """
    Hybrid flow: run a recorded Playwright script, then run an LLM task.
    """
    tab_components: dict[str, Any] = {}

    with gr.Column():
        gr.Markdown(
            """
            ### Hybrid Flow (Hard-coded + Prompt)
            Step 1: Run a recorded Playwright script  
            Step 2: Run an LLM task with browser-use
            """
        )

        script_path = gr.Textbox(
            label="Recorded Script Path",
            value=os.getenv("DEMO_OUTPUT_PATH", "./tmp/demo/recording.py"),
            interactive=True,
        )
        script_env = gr.Textbox(
            label="Script Env (JSON)",
            placeholder='{"SKU":"VN000D93BA2"}',
            interactive=True,
        )
        prompt_task = gr.Textbox(
            label="LLM Task After Script",
            placeholder="Continue from the current page and download images...",
            lines=3,
            interactive=True,
        )
        status = gr.Markdown(value="Ready.")
        run_btn = gr.Button("▶️ Run Hybrid Flow", variant="primary")

    tab_components.update(
        dict(
            script_path=script_path,
            script_env=script_env,
            prompt_task=prompt_task,
            status=status,
            run_btn=run_btn,
        )
    )
    webui_manager.add_components("hybrid_flow", tab_components)

    async def run_wrapper(values: Dict[gr.components.Component, Any]):
        def get_setting(key, default=None):
            comp = webui_manager.id_to_component.get(f"agent_settings.{key}")
            return values.get(comp, default) if comp else default

        def get_browser_setting(key, default=None):
            comp = webui_manager.id_to_component.get(f"browser_settings.{key}")
            return values.get(comp, default) if comp else default

        script = values.get(script_path, "").strip()
        task = values.get(prompt_task, "").strip()
        env_json = values.get(script_env, "").strip() or None

        llm_provider_name = get_setting("llm_provider", None)
        llm_model_name = get_setting("llm_model_name", None)
        llm_temperature = get_setting("llm_temperature", 0.6)
        llm_base_url = get_setting("llm_base_url") or None
        llm_api_key = get_setting("llm_api_key") or None
        use_vision = get_setting("use_vision", True)
        max_steps = get_setting("max_steps", 100)
        max_actions = get_setting("max_actions", 10)

        browser_binary_path = get_browser_setting("browser_binary_path") or None
        browser_user_data_dir = get_browser_setting("browser_user_data_dir") or None
        use_own_browser = get_browser_setting("use_own_browser", False)
        headless = get_browser_setting("headless", False)
        disable_security = get_browser_setting("disable_security", False)
        accept_downloads = get_browser_setting("accept_downloads", True)
        window_w = int(get_browser_setting("window_w", 1280))
        window_h = int(get_browser_setting("window_h", 1100))
        cdp_url = get_browser_setting("cdp_url") or None
        wss_url = get_browser_setting("wss_url") or None
        save_download_path = get_browser_setting("save_download_path", "./tmp/downloads")

        if not use_own_browser:
            browser_binary_path = None
            browser_user_data_dir = None

        cdp_endpoint = wss_url or cdp_url or None
        browser_kwargs = {
            "headless": headless,
            "disable_security": disable_security,
            "accept_downloads": accept_downloads,
            "executable_path": browser_binary_path or os.getenv("BROWSER_PATH") or None,
            "user_data_dir": browser_user_data_dir or os.getenv("BROWSER_USER_DATA") or None,
            "cdp_url": cdp_endpoint,
            "window_size": {"width": window_w, "height": window_h},
            "downloads_path": save_download_path,
        }

        try:
            await run_hybrid_flow(
                script_path=script,
                task=task,
                llm_provider_name=llm_provider_name,
                llm_model_name=llm_model_name,
                llm_temperature=llm_temperature,
                llm_base_url=llm_base_url,
                llm_api_key=llm_api_key,
                use_vision=use_vision,
                max_steps=max_steps,
                max_actions=max_actions,
                browser_kwargs=browser_kwargs,
                script_env_json=env_json,
                cdp_url=cdp_endpoint,
            )
        except Exception as exc:
            return {status: gr.update(value=f"❌ Hybrid flow failed: {exc}")}

        return {status: gr.update(value="✅ Hybrid flow finished.")}

    run_btn.click(
        fn=run_wrapper,
        inputs=webui_manager.get_components(),
        outputs=[status],
    )

    return
