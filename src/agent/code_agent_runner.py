import os
import uuid
from pathlib import Path
from typing import Optional

from browser_use.browser.session import BrowserSession
from browser_use.code_use.notebook_export import session_to_python_script
from browser_use.code_use.service import CodeAgent
from browser_use.llm.browser_use.chat import ChatBrowserUse


async def create_flow_script(
    task: str,
    output_dir: Optional[str] = None,
    browser_kwargs: Optional[dict] = None,
    use_vision: bool = True,
    max_steps: int = 100,
    api_key: Optional[str] = None,
) -> tuple[str, str, str]:
    """
    Run CodeAgent and export a Python script for the task.
    """
    key = api_key or os.getenv("BROWSER_USE_API_KEY", "")
    if not key:
        raise ValueError("BROWSER_USE_API_KEY is required to generate a flow script.")

    flow_dir = Path(output_dir or os.getenv("FLOW_STORAGE_DIR", "./tmp/flows"))
    run_id = uuid.uuid4().hex
    run_dir = flow_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    browser_session = BrowserSession(**(browser_kwargs or {}))
    agent = CodeAgent(
        task=task,
        llm=ChatBrowserUse(api_key=key),
        browser_session=browser_session,
        use_vision=use_vision,
        max_steps=max_steps,
    )

    try:
        await agent.run()
        script_text = session_to_python_script(agent)
        script_path = run_dir / "flow.py"
        script_path.write_text(script_text, encoding="utf-8")
        return run_id, str(script_path), script_text
    finally:
        try:
            await browser_session.kill()
        except Exception:
            pass
