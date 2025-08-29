import asyncio
import json
import logging
import os
import httpx
from typing import Annotated
from dotenv import load_dotenv

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from pyngrok import ngrok
import socket

# Load environment variables
load_dotenv()

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.network.fastapi_websocket import FastAPIWebsocketTransport, FastAPIWebsocketParams
from loguru import logger

ngrok_url: str = ""
agent_config: dict = {}

def setup_ngrok_tunnel(port: int = 8080) -> str:
    """
    Setup ngrok tunnel for the local server
    Returns the public ngrok URL
    """
    global ngrok_url

    if ngrok_url and ngrok_url != "":
        return ngrok_url

    try:
        logger.info(f"Setting up ngrok tunnel for port {port}...")

        # Kill any existing tunnels
        ngrok.kill()

        # Setup tunnel (this is synchronous but fast)
        tunnel = ngrok.connect(port, "http")
        ngrok_url = tunnel.public_url  # type: ignore

        logger.info(f"Ngrok tunnel established: {ngrok_url}")
        return ngrok_url

    except Exception as e:
        logger.warning(f"Failed to establish ngrok tunnel: {e}")

        # Fallback to localhost for development
        fallback_url = f"http://localhost:{port}"
        ngrok_url = fallback_url
        logger.info(f"Using fallback URL: {fallback_url}")
        return fallback_url

app = FastAPI(title="Pipecat Voice Agent Bridge")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def get():
    with open("static/index.html", "r") as file:
        return HTMLResponse(content=file.read(), status_code=200)

@app.post("/join-meeting")
async def join_meeting(
    meetingUrl: str = Form(...),
    wsUrl: str = Form(...),
    prompt: str = Form("You are a super duper helpful assistant"),
    greeting: str = Form("Hello! I'm your voice assistant. How can I help you today?"),
    model: str = Form("aura-2-thalia-en")
):
    global agent_config
    
    # Store agent configuration from form
    agent_config["prompt"] = prompt
    agent_config["greeting"] = greeting
    agent_config["model"] = model
    
    logger.info(f"Meeting URL: {meetingUrl}")
    logger.info(f"WebSocket Tunnel URL: {wsUrl}")
    logger.info(f"Agent Prompt: {agent_config['prompt']}")
    logger.info(f"Agent Greeting: {agent_config['greeting']}")
    logger.info(f"Agent Model: {agent_config['model']}")
    
    # Prepare data for Attendee API
    attendee_data = {
        "meeting_url": meetingUrl,
        "bot_name": "Pipecat Voice Agent",
        "websocket_settings": {
            "audio": {
                "url": wsUrl,
                "sample_rate": 16000
            }
        }
    }
    
    # Get API key from environment
    attendee_api_key = os.getenv("ATTENDEE_API_KEY")
    if not attendee_api_key:
        raise HTTPException(status_code=500, detail="ATTENDEE_API_KEY not set in environment")
    
    # Make API request to Attendee
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://app.attendee.dev/api/v1/bots",
                json=attendee_data,
                headers={
                    "Authorization": f"Token {attendee_api_key}",
                    "Content-Type": "application/json"
                }
            )
            
            if response.status_code >= 200 and response.status_code < 300:
                logger.info("Bot launch successful")
                return {"message": "Success! The bot will join the meeting in 30 seconds and start speaking 30 seconds after joining."}
            else:
                logger.error(f"Bot launch failed: {response.status_code} - {response.text}")
                raise HTTPException(status_code=500, detail=f"Error launching bot: {response.status_code} - {response.text}")
    except Exception as e:
        logger.error(f"Error launching bot: {e}")
        raise HTTPException(status_code=500, detail=f"Error launching bot: {str(e)}")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket connection established")
    
    # Use global agent configuration
    global agent_config
    
    # Initialize with default values if not set
    if not agent_config:
        agent_config = {
            "prompt": "You are a super duper helpful assistant",
            "greeting": "Hello! I'm your voice assistant. How can I help you today?",
            "model": "aura-2-thalia-en"
        }
    
    try:
        # Initialize Pipecat components
        transport_params = FastAPIWebsocketParams(add_wav_header=True)
        transport = FastAPIWebsocketTransport(websocket, transport_params)
        
        # Initialize STT service (Deepgram)
        stt = DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY", ""))
        
        # Initialize LLM service (OpenAI)
        llm = OpenAILLMService(api_key=os.getenv("OPENAI_API_KEY"), model="gpt-4o")
        
        # Create context with dynamic prompt
        messages = [
            {
                "role": "system",
                "content": agent_config["prompt"]
            }
        ]
        context = OpenAILLMContext(messages) # type: ignore 
        context_aggregator = llm.create_context_aggregator(context)
        
        # Create pipeline
        pipeline = Pipeline([
            transport.input(),
            stt,
            context_aggregator.user(),
            llm,
            context_aggregator.assistant(),
            transport.output()
        ])
        
        # Create task and run pipeline
        task = PipelineTask(pipeline)
        runner = PipelineRunner()
        
        # Create tasks for concurrent execution
        pipeline_task = asyncio.create_task(runner.run(task))
        message_task = asyncio.create_task(handle_websocket_messages(websocket, transport, task))
        
        # Wait for either task to complete
        done, pending = await asyncio.wait(
            [pipeline_task, message_task], 
            return_when=asyncio.FIRST_COMPLETED
        )
        
        # Cancel pending tasks
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        # Check for exceptions
        for task in done:
            try:
                await task
            except Exception as e:
                logger.error(f"Task failed: {e}")
                raise
                
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        await websocket.close()
        logger.info("WebSocket connection closed")

async def handle_websocket_messages(websocket: WebSocket, transport, pipeline_task):
    """
    Handle incoming WebSocket messages concurrently with pipeline execution
    """
    try:
        while True:
            try:
                # Wait for message with timeout to allow checking pipeline status
                data = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                message = json.loads(data)
                
                if message.get("type") == "audio":
                    # Send audio data to Pipecat transport
                    await transport.send_audio(message.get("data"))
                elif message.get("type") == "config":
                    # Update configuration
                    config = message.get("data", {})
                    logger.info(f"Configuration updated: {config}")
                # Other message types can be handled here
                pass
                    
            except asyncio.TimeoutError:
                # Check if pipeline task is still running
                if pipeline_task.done():
                    break
                continue
                
    except Exception as e:
        logger.error(f"Error in WebSocket message handler: {e}")
        raise


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))

    # Setup ngrok tunnel on startup
    logger.info("Setting up ngrok tunnel...")
    public_url = setup_ngrok_tunnel(port)
    logger.info(f"Server will be available at: {public_url}")
    logger.info(f"Meeting link endpoint: {public_url}/meeting-link")

    # Start the server
    uvicorn.run(app, host="0.0.0.0", port=port)
