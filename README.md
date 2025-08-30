# Pipecat Voice Agent with Attendee

This project demonstrates how to create a real-time voice agent using Pipecat framework in Python with FastAPI, integrated with Attendee's meeting bot API.

## Features

- Real-time voice-to-voice conversational AI using Pipecat
- Integration with Deepgram for speech-to-text
- Integration with OpenAI for language processing
- Integration with Attendee API for meeting bot functionality
- WebSocket-based communication between browser and server
- Configurable agent personality and voice

## Prerequisites

1. Python 3.10 or higher
2. [UV](https://github.com/astral-sh/uv) for dependency management
3. Pipecat framework
4. API keys for:
   - Deepgram (for STT/TTS)
   - OpenAI (for LLM)
   - Attendee (for meeting bot API)
5. Ngrok or similar tunneling service for WebSocket connections

## Setup Instructions

1. Clone the repository
2. Install dependencies using UV:
   ```
   uv sync
   ```
3. Copy `.env.example` to `.env` and fill in your API keys:
   ```
   DEEPGRAM_API_KEY=your_deepgram_api_key
   OPENAI_API_KEY=your_openai_api_key
   ATTENDEE_API_KEY=your_attendee_api_key
   ATTENDEE_API_HOST=https://app.attendee.dev
   NGROK_URL=wss://your-ngrok-url.ngrok-free.app
   PORT=8000
   ```
4. Run the application:
   ```
   python app/main.py
   ```

## Usage

1. Start ngrok or your preferred tunneling service to expose port 8000
2. Open `http://localhost:8000` in your browser
3. Configure the voice agent:
   - Meeting URL: The URL of the meeting the bot should join
   - WebSocket Tunnel URL: Your ngrok WebSocket URL
   - Agent Prompt: Customize the AI assistant's personality
   - Greeting Message: Set what the agent says when it joins
   - Voice Model: Choose from available Deepgram voice models
4. Click "Launch Voice Agent" to start the bot

## Project Structure

- `app/main.py`: Main FastAPI application with WebSocket endpoint
- `static/index.html`: Frontend interface
- `pyproject.toml`: Project dependencies and metadata
- `.env.example`: Environment variable template

## How It Works

1. The browser connects to the FastAPI server via WebSocket
2. User configures the voice agent through the web interface
3. When "Launch Voice Agent" is clicked, the server calls Attendee API to join the meeting
4. Audio is streamed in real-time between the browser and the Pipecat pipeline
5. Pipecat processes the audio through:
   - Deepgram STT (speech-to-text)
   - OpenAI LLM (language processing)
   - Deepgram TTS (text-to-speech)
6. The processed audio is sent back to the browser and into the meeting

## API Endpoints

- `GET /`: Serve the web interface
- `WebSocket /ws`: Handle real-time audio streaming and bot configuration

## Configuration

The application can be configured using environment variables:

- `DEEPGRAM_API_KEY`: Deepgram API key for speech processing
- `OPENAI_API_KEY`: OpenAI API key for language processing
- `ATTENDEE_API_KEY`: Attendee API key for meeting bot functionality
- `ATTENDEE_API_HOST`: Attendee API host URL (default: https://app.attendee.dev)
- `NGROK_URL`: Ngrok URL for WebSocket connections (default: ws://localhost:8080)
- `PORT`: Port to run the server on (default: 8080)
