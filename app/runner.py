import base64
import json
import os
from fastapi.websockets import WebSocketState
from dotenv import load_dotenv

from fastapi import (
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.templating import Jinja2Templates
from pipecat.serializers.base_serializer import FrameSerializer, FrameSerializerType
from pipecat.processors.audio.audio_buffer_processor import AudioBufferProcessor
from pipecat.services.deepgram.tts import DeepgramTTSService
from pipecat.audio.vad.silero import SileroVADAnalyzer

# Set up Jinja2 templates
templates = Jinja2Templates(directory="static")


# Load environment variables
load_dotenv()

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.frames.frames import (
    AudioRawFrame,
    Frame,
    InputAudioRawFrame,
    LLMRunFrame,
)
from loguru import logger

from pipecat.transports.network.fastapi_websocket import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)


class AttendeeFrameSerializer(FrameSerializer):
    @property
    def type(self) -> FrameSerializerType:
        return FrameSerializerType.TEXT

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, AudioRawFrame):
            audio_b64 = base64.b64encode(frame.audio).decode("utf-8")
            attendee_output = {
                "trigger": "realtime_audio.bot_output",
                "data": {
                    "chunk": audio_b64,
                    "sample_rate": frame.sample_rate,
                    "num_channels": frame.num_channels,
                },
            }
            return json.dumps(attendee_output)
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        try:
            if isinstance(data, bytes):
                data = data.decode("utf-8")

            json_data = json.loads(data)

            if (
                json_data.get("trigger") == "realtime_audio.mixed"
                and "data" in json_data
            ):
                audio_data = json_data["data"]

                chunk_data = base64.b64decode(audio_data["chunk"])
                sample_rate = audio_data.get("sample_rate", 16000)

                audio_frame = InputAudioRawFrame(
                    audio=chunk_data, sample_rate=sample_rate, num_channels=1
                )

                return audio_frame
        except (json.JSONDecodeError, Exception, KeyError):
            pass
        return None


async def run_bot(websocket: WebSocket, agent_config: dict):
    try:
        messages = [{"role": "system", "content": agent_config["prompt"]}]

        transport_params = FastAPIWebsocketParams(
            add_wav_header=False,
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_analyzer=SileroVADAnalyzer(),
            serializer=AttendeeFrameSerializer(),
        )
        transport = FastAPIWebsocketTransport(websocket, transport_params)

        stt = DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY", ""))
        llm = OpenAILLMService(api_key=os.getenv("OPENAI_API_KEY"), model="gpt-4o")
        context = OpenAILLMContext(messages)  # type: ignore
        context_aggregator = llm.create_context_aggregator(context)

        tts = DeepgramTTSService(
            api_key=os.getenv("DEEPGRAM_API_KEY", ""),
            voice=agent_config["voice"],
            sample_rate=16000,
            encoding="linear16",
        )

        audiobuffer = AudioBufferProcessor()
        pipeline = Pipeline(
            [
                transport.input(),
                stt,
                context_aggregator.user(),
                llm,
                tts,
                transport.output(),
                audiobuffer,
                context_aggregator.assistant(),
            ]
        )

        task = PipelineTask(
            pipeline,
            params=PipelineParams(
                enable_metrics=True,
                audio_in_sample_rate=16000,
                audio_out_sample_rate=16000,
                enable_usage_metrics=True,
            ),
        )

        @transport.event_handler("on_client_connected")
        async def on_client_connected(transport, participant):
            logger.info(f"Client connected: {participant}")
            await task.queue_frames([LLMRunFrame()])

        @transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(transport, participant):
            logger.info(f"Client disconnected: {participant}")
            await task.cancel()

        runner = PipelineRunner(handle_sigint=False, force_gc=True)
        await runner.run(task)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        if websocket.state == WebSocketState.CONNECTED:
            await websocket.close()
        logger.info("WebSocket connection closed")
