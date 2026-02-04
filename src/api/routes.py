import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from browser_use import Agent
from browser_use.browser.session import BrowserSession

from src.agent.code_agent_runner import create_flow_script
from src.utils import llm_provider
from src.workflow.store import save_workflow, load_workflow, list_workflows
from src.workflow.runner import run_workflow

api_router = APIRouter()


class BrowserConfig(BaseModel):
    headless: bool = False
    disable_security: bool = False
    accept_downloads: bool = True
    executable_path: Optional[str] = None
    user_data_dir: Optional[str] = None
    cdp_url: Optional[str] = None
    wss_url: Optional[str] = None
    window_w: int = 1280
    window_h: int = 1100
    downloads_path: Optional[str] = "./tmp/downloads"


class RunAgentRequest(BaseModel):
    task: str = Field(..., min_length=1)
    llm_provider: str = "google"
    llm_model: str = "gemini-3-pro-preview"
    temperature: float = 0.6
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    use_vision: bool = True
    max_steps: int = 100
    max_actions: int = 10
    browser: BrowserConfig = BrowserConfig()


class RunAgentResponse(BaseModel):
    run_id: str
    final_result: Optional[str]
    errors: list[str]
    history_path: Optional[str]


class ExportFlowRequest(BaseModel):
    task: str = Field(..., min_length=1)
    use_vision: bool = True
    max_steps: int = 100
    output_dir: Optional[str] = None
    browser: BrowserConfig = BrowserConfig()
    browser_use_api_key: Optional[str] = None


class ExportFlowResponse(BaseModel):
    run_id: str
    script_path: str
    script_text: str


class WorkflowPayload(BaseModel):
    name: Optional[str] = None
    nodes: list[dict]
    edges: list[dict]


def _build_browser_kwargs(browser: BrowserConfig) -> dict:
    return {
        "headless": browser.headless,
        "disable_security": browser.disable_security,
        "accept_downloads": browser.accept_downloads,
        "executable_path": browser.executable_path or os.getenv("BROWSER_PATH") or None,
        "user_data_dir": browser.user_data_dir or os.getenv("BROWSER_USER_DATA") or None,
        "cdp_url": browser.wss_url or browser.cdp_url or None,
        "window_size": {"width": browser.window_w, "height": browser.window_h},
        "downloads_path": browser.downloads_path,
    }


@api_router.post("/agent/run", response_model=RunAgentResponse)
async def run_agent(request: RunAgentRequest):
    try:
        llm = llm_provider.get_llm_model(
            provider=request.llm_provider,
            model_name=request.llm_model,
            temperature=request.temperature,
            base_url=request.base_url,
            api_key=request.api_key,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    browser_session = BrowserSession(**_build_browser_kwargs(request.browser))
    agent = Agent(
        task=request.task,
        llm=llm,
        browser_session=browser_session,
        use_vision=request.use_vision,
        max_actions_per_step=request.max_actions,
        source="api",
    )

    run_id = uuid.uuid4().hex
    history_dir = Path(os.getenv("FLOW_RUNS_DIR", "./tmp/runs")) / run_id
    history_dir.mkdir(parents=True, exist_ok=True)
    history_path = history_dir / f"{run_id}.json"

    try:
        history = await agent.run(max_steps=request.max_steps)
        agent.save_history(history_path)
        return RunAgentResponse(
            run_id=run_id,
            final_result=history.final_result(),
            errors=[str(err) for err in history.errors() if err],
            history_path=str(history_path),
        )
    finally:
        try:
            await browser_session.kill()
        except Exception:
            pass


@api_router.post("/flow/export", response_model=ExportFlowResponse)
async def export_flow(request: ExportFlowRequest):
    browser_kwargs = _build_browser_kwargs(request.browser)
    output_dir = request.output_dir or os.getenv("FLOW_STORAGE_DIR", "./tmp/flows")
    try:
        run_id, script_path, script_text = await create_flow_script(
            task=request.task,
            output_dir=output_dir,
            browser_kwargs=browser_kwargs,
            use_vision=request.use_vision,
            max_steps=request.max_steps,
            api_key=request.browser_use_api_key,
        )
        return ExportFlowResponse(
            run_id=run_id,
            script_path=script_path,
            script_text=script_text,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@api_router.get("/workflows")
def api_list_workflows():
    return {"workflows": list_workflows()}


@api_router.post("/workflows/save")
def api_save_workflow(payload: WorkflowPayload):
    wid = save_workflow(payload.model_dump())
    return {"id": wid}


@api_router.get("/workflows/{workflow_id}")
def api_load_workflow(workflow_id: str):
    try:
        return load_workflow(workflow_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Workflow not found")


@api_router.post("/workflows/run")
async def api_run_workflow(payload: WorkflowPayload):
    llm_provider_name = os.getenv("DEFAULT_LLM", "google")
    llm_model_name = os.getenv("DEFAULT_LLM_MODEL", "gemini-3-pro-preview")
    llm_temperature = float(os.getenv("DEFAULT_LLM_TEMPERATURE", "0.6"))
    llm_base_url = os.getenv("DEFAULT_LLM_BASE_URL") or None
    llm_api_key = os.getenv("DEFAULT_LLM_API_KEY") or None

    browser_kwargs = {
        "headless": False,
        "disable_security": False,
        "accept_downloads": True,
    }

    result = await run_workflow(
        payload.model_dump(),
        llm_provider_name=llm_provider_name,
        llm_model_name=llm_model_name,
        llm_temperature=llm_temperature,
        llm_base_url=llm_base_url,
        llm_api_key=llm_api_key,
        use_vision=True,
        max_steps=100,
        max_actions=10,
        browser_kwargs=browser_kwargs,
    )
    return result
