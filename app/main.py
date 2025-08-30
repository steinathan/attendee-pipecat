import os
import httpx
from dotenv import load_dotenv

from fastapi import (
    FastAPI,
    WebSocket,
    HTTPException,
    Form,
    Request,
)
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates

from runner import run_bot

import uvicorn


load_dotenv()

from loguru import logger


agent_config: dict | None = None

app = FastAPI(title="Pipecat Voice Agent Bridge")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory="static")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def get(request: Request):
    # Get ngrok URL from environment variables
    ngrok_url = os.getenv("NGROK_URL")
    if not ngrok_url:
        # Fallback to localhost for development
        port = int(os.getenv("PORT", 8080))
        ngrok_url = f"ws://replace-me:{port}"
    
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "ws_url": f"{ngrok_url.replace('http', 'ws')}/ws"},
    )


@app.post("/join-meeting")
async def join_meeting(
    meetingUrl: str = Form(...),
    wsUrl: str = Form(...),
    prompt: str = Form(...),
    greeting: str = Form(...),
    model: str = Form(...),
    voice: str = Form(...),
):
    global agent_config

    agent_config = {
        "prompt": prompt,
        "greeting": greeting,
        "model": model,
        "voice": voice,
    }

    logger.debug(f"Meeting URL: {meetingUrl}")
    logger.debug(f"WebSocket Tunnel URL: {wsUrl}")
    logger.debug(f"Agent Prompt: {agent_config['prompt']}")
    logger.debug(f"Agent Greeting: {agent_config['greeting']}")
    logger.debug(f"Agent Model: {agent_config['model']}")
    logger.debug(f"Agent Voice: {agent_config['voice']}")

    attendee_payload = {
        "meeting_url": meetingUrl,
        "bot_name": "Pipecat Voice Agent",
        "websocket_settings": {"audio": {"url": wsUrl, "sample_rate": 16000}},
    }

    attendee_api_key = os.getenv("ATTENDEE_API_KEY")
    if not attendee_api_key:
        raise HTTPException(
            status_code=500, detail="ATTENDEE_API_KEY not set in environment"
        )

    attendee_api_host = os.getenv("ATTENDEE_API_HOST", "https://app.attendee.dev")
    attendee_api_url = f"{attendee_api_host}/api/v1/bots"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                attendee_api_url,
                json=attendee_payload,
                headers={
                    "Authorization": f"Token {attendee_api_key}",
                    "Content-Type": "application/json",
                },
            )

            if response.status_code >= 200 and response.status_code < 300:
                logger.info("Bot launched successful")
                return {
                    "message": "Success! The bot will join the meeting in 30 seconds and start speaking soon after joining."
                }
            else:
                logger.error(
                    f"Bot launch failed: {response.status_code} - {response.text}"
                )
                raise HTTPException(
                    status_code=500,
                    detail=f"Error launching bot: {response.status_code} - {response.text}",
                )
    except Exception as e:
        logger.error(f"Error launching bot: {e}")
        raise HTTPException(status_code=500, detail=f"Error launching bot: {str(e)}")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket connection established")

    global agent_config

    if not agent_config:
        logger.warning("Agent configuration not set. Using default values.")
        agent_config = {
            "prompt": "You are a super duper helpful assistant",
            "greeting": "Hello! I'm your voice assistant. How can I help you today?",
            "voice": "aura-2-thalia-en",
            "model": "gpt-4o",
        }

    # kick off the bot
    await run_bot(websocket, agent_config)


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    logger.debug(
        f"Attendee host: {os.getenv('ATTENDEE_API_HOST', 'https://app.attendee.dev')}"
    )

    uvicorn.run(app, host="0.0.0.0", port=port)
