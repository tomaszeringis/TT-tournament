"""
UmpireEngine - Real-time table tennis commentary service.

Implements a pipeline where:
- faster-whisper listens to microphone and provides real-time transcription
- Ollama receives the transcript and generates energetic umpire commentary
- RealtimeTTS consumes the response stream with immediate playback on sentence boundaries
- All components run concurrently using asyncio
"""

import asyncio
import logging
import os
from typing import Optional, AsyncGenerator, Callable, List, Dict, Any
from dataclasses import dataclass, field

import ollama
from faster_whisper import WhisperModel

# pyaudio (and RealtimeTTS) are only needed for live microphone capture, which
# requires system libraries (portaudio) and is unavailable on Streamlit Cloud.
# Import them defensively so the module still imports where they are absent.
try:
    import pyaudio
except ImportError:
    pyaudio = None

try:
    from RealtimeTTS import TextToAudioStream, GTTSEngine
except ImportError:
    TextToAudioStream = None
    GTTSEngine = None
from tournament_platform.services.rules_retrieval import RulesRetriever
from tournament_platform.config import settings

# Configure logging
os.makedirs(settings.LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(settings.LOG_DIR, "umpire_engine.log"),
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Table tennis terminology for initial prompt
TABLE_TENNIS_TERMS = """
let, rally, game point, deuce, backhand, forehand, serve, spin, topspin, backspin,
chop, loop, smash, block, push, flick, paddle, table, net, edge, corner,
fault, out, in, point, match, set, game, tie, break, hold, receive,
service, return, attack, defense, counter, placement, footwork, stance,
grip, shakehands, penhold, shake hand, shake-hand, shake hand grip,
tournament, championship, final, semi-final, quarter-final, round,
referee, umpire, score, scorekeeper, match ball, match point
""".strip()


@dataclass
class UmpireConfig:
    """Configuration for UmpireEngine."""
    whisper_model_size: str = settings.WHISPER_MODEL_SIZE
    ollama_model: str = settings.OLLAMA_MODEL
    tts_sample_rate: int = settings.TTS_SAMPLE_RATE
    tts_chunk_size: int = settings.TTS_CHUNK_SIZE
    max_response_words: int = 15
    audio_format: int = settings.AUDIO_FORMAT
    channels: int = settings.AUDIO_CHANNELS
    rate: int = settings.AUDIO_RATE
    chunk: int = settings.AUDIO_CHUNK
    silence_threshold: int = settings.AUDIO_SILENCE_THRESHOLD
    min_silence_duration: float = settings.AUDIO_MIN_SILENCE_DURATION


class UmpireEngine:
    """
    Real-time table tennis umpire commentary engine.
    
    Uses faster-whisper for speech-to-text, Ollama for LLM processing,
    and RealtimeTTS for text-to-speech with streaming playback.
    """
    
    def __init__(self, config: Optional[UmpireConfig] = None):
        self.config = config or UmpireConfig()
        
        # Detect CUDA availability for GPU acceleration
        self.cuda_available = self._check_cuda()
        self.device = "cuda" if self.cuda_available else "cpu"
        
        # Initialize components
        self._init_whisper()
        self._init_tts()
        self._init_rules_retriever()
        
        # State management
        self._running = False
        self._audio_stream: "Optional[pyaudio.Stream]" = None
        self._pyaudio: "Optional[pyaudio.PyAudio]" = None
        self._tts_buffer: str = ""
        self._current_commentary_task: Optional[asyncio.Task] = None
        self._transcript_queue: asyncio.Queue = asyncio.Queue()
        
        # System prompt for the umpire personality
        self._umpire_system_prompt = (
            "You are an energetic, biased table tennis umpire. "
            "You are passionate about the game and have strong opinions about players and plays. "
            "Keep responses short, high-energy, and under 15 words. "
            "Use table tennis terminology like 'let', 'rally', 'game point', 'deuce', 'backhand', 'forehand', etc. "
            "Be dramatic and exciting - you're calling the match live! "
            "Don't be too technical, focus on the excitement and flow of the match. "
            "If you're unsure about something, make an enthusiastic guess rather than saying you don't know."
        )
        
        # System prompt for the rules oracle
        self._rules_oracle_system_prompt = (
            "You are the LITIT Tournament Rules Oracle. "
            "Use the provided rule context to answer the user's question concisely. "
            "Be friendly but authoritative. "
            "If the answer is not in the rules, say you are unsure."
        )
        
        logger.info(f"UmpireEngine initialized with device: {self.device}")
    
    def _check_cuda(self) -> bool:
        """Check if CUDA-enabled GPU is available."""
        try:
            import torch
            cuda_available = torch.cuda.is_available()
            if cuda_available:
                device_name = torch.cuda.get_device_name(0)
                logger.info(f"CUDA GPU detected: {device_name}")
            return cuda_available
        except ImportError:
            logger.warning("PyTorch not installed, defaulting to CPU")
            return False
    
    def _init_whisper(self):
        """Initialize faster-whisper model with appropriate device."""
        compute_type = "float16" if self.cuda_available else "int8"
        self.whisper_model = WhisperModel(
            self.config.whisper_model_size,
            device=self.device,
            compute_type=compute_type
        )
        logger.info(f"Whisper model '{self.config.whisper_model_size}' loaded on {self.device}")
    
    def _init_tts(self):
        """Initialize RealtimeTTS engine."""
        self.tts_engine = GTTSEngine()
        self.tts_stream = TextToAudioStream(
            engine=self.tts_engine
        )
        logger.info("TTS engine initialized")
     
    def _init_rules_retriever(self):
        """Initialize the RulesRetriever for RAG-based rule queries."""
        self.rules_retriever = RulesRetriever()
        logger.info("RulesRetriever initialized for Voice Rules Chat")
     
    def _get_ollama_model(self) -> str:
        """Get available Ollama model with fallback.

        In Cloud/external API mode this returns the configured model without
        touching the local Ollama client (the bridge governs availability).
        """
        try:
            from tournament_platform.app.services.ai_provider import resolve_provider

            if resolve_provider() == "api_bridge":
                return self.config.ollama_model
        except Exception:
            pass

        try:
            available_models_resp = ollama.list()
            
            if hasattr(available_models_resp, 'models'):
                model_names = [m.model for m in available_models_resp.models]
            else:
                model_names = [m.get('name') for m in available_models_resp.get('models', [])]
            
            # Check for preferred model
            if self.config.ollama_model in model_names:
                return self.config.ollama_model
            
            # Try fallbacks
            fallbacks = ["llama3.1:8b", "llama3:latest", "llama3:8b", "llama3.2:3b", "llama3.2:1b"]
            for fallback in fallbacks:
                if fallback in model_names:
                    logger.info(f"Ollama model fallback: {self.config.ollama_model} -> {fallback}")
                    return fallback
            
            logger.warning(f"No Ollama model found, using default: {self.config.ollama_model}")
            return self.config.ollama_model
            
        except Exception as e:
            logger.error(f"Error checking Ollama models: {e}")
            return self.config.ollama_model
    
    async def _audio_capture_loop(self):
        """Continuously capture audio from microphone and transcribe."""
        self._pyaudio = pyaudio.PyAudio()
        
        try:
            self._audio_stream = self._pyaudio.open(
                format=self.config.audio_format,
                channels=self.config.channels,
                rate=self.config.rate,
                input=True,
                frames_per_buffer=self.config.chunk
            )
            
            logger.info("Audio capture started")
            
            while self._running:
                try:
                    # Read audio chunk
                    data = self._audio_stream.read(
                        self.config.chunk,
                        exception_on_overflow=False
                    )
                    
                    # Check for silence
                    if self._is_silence(data):
                        continue
                    
                    # Transcribe the audio
                    transcript = await self._transcribe_chunk(data)
                    
                    if transcript:
                        await self._transcript_queue.put(transcript)
                        logger.debug(f"Transcribed: {transcript}")
                        
                except Exception as e:
                    logger.error(f"Audio capture error: {e}")
                    await asyncio.sleep(0.1)
                    
        except Exception as e:
            logger.error(f"Audio stream error: {e}")
        finally:
            self._cleanup_audio()
    
    def _is_silence(self, data: bytes) -> bool:
        """Check if audio data is below silence threshold."""
        try:
            import audioop
            rms = audioop.rms(data, 2)  # 2 bytes per sample for paInt16
            return rms < self.config.silence_threshold
        except Exception:
            return False
    
    async def _transcribe_chunk(self, audio_data: bytes) -> str:
        """Transcribe audio chunk using faster-whisper."""
        try:
            # Save to temp file for faster-whisper
            import tempfile
            import wave
            
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                with wave.open(f, 'wb') as wf:
                    wf.setnchannels(self.config.channels)
                    wf.setsampwidth(2)
                    wf.setframerate(self.config.rate)
                    wf.writeframes(audio_data)
                temp_path = f.name
            
            # Transcribe with initial prompt for table tennis terms
            segments, _ = self.whisper_model.transcribe(
                temp_path,
                initial_prompt=TABLE_TENNIS_TERMS,
                beam_size=5
            )
            
            # Clean up temp file
            os.unlink(temp_path)
            
            # Combine segments
            text = " ".join(seg.text for seg in segments).strip()
            return text
            
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return ""
    
    async def _llm_process_stream(
        self,
        transcript: str
    ) -> AsyncGenerator[str, None]:
        """Stream LLM response for a transcript.

        In Cloud/external API mode it uses the FastAPI bridge (non-streaming)
        and yields the completed commentary. Locally it streams from Ollama.
        """
        try:
            from tournament_platform.app.services.ai_provider import resolve_provider

            if resolve_provider() == "api_bridge":
                from tournament_platform.app.services.ai_provider import ollama_chat

                result = ollama_chat(
                    messages=[
                        {"role": "system", "content": self._umpire_system_prompt},
                        {"role": "user", "content": transcript},
                    ],
                    model=self._get_ollama_model(),
                    temperature=0.3,
                )
                if result and result.get("ok"):
                    yield result.get("message", "")
                else:
                    yield f"Error: {result.get('error') if result else 'Ollama unavailable via API'}"
                return

            model = self._get_ollama_model()

            # ollama.chat with stream=True returns a sync generator, run in executor
            loop = asyncio.get_event_loop()

            def sync_stream():
                return ollama.chat(
                    model=model,
                    messages=[
                        {"role": "system", "content": self._umpire_system_prompt},
                        {"role": "user", "content": transcript}
                    ],
                    stream=True,
                    options={"num_predict": 150}  # Limit response length to prevent infinite generation
                )

            response_gen = await loop.run_in_executor(None, sync_stream)

            chunk_count = 0
            max_chunks = 200  # Safety limit to prevent infinite streaming
            for chunk in response_gen:
                chunk_count += 1
                if chunk_count > max_chunks:
                    logger.warning(f"LLM stream exceeded {max_chunks} chunks, stopping")
                    yield " [Response truncated due to length limit]"
                    break
                if 'message' in chunk and 'content' in chunk['message']:
                    yield chunk['message']['content']

        except Exception as e:
            logger.error(f"LLM processing error: {e}")
            yield f"Error: {str(e)}"
    
    def _find_sentence_boundary(self, text: str) -> int:
        """Find the position of the first sentence boundary."""
        for i, char in enumerate(text):
            if char in '.!?':
                return i + 1
        return -1
    
    async def _tts_playback_stream(
        self, 
        text_stream: AsyncGenerator[str, None]
    ):
        """Consume LLM stream and play TTS on sentence boundaries."""
        buffer = ""
        
        async for text_chunk in text_stream:
            buffer += text_chunk
            
            # Check for sentence boundary
            boundary_pos = self._find_sentence_boundary(buffer)
            
            if boundary_pos > 0:
                sentence = buffer[:boundary_pos]
                buffer = buffer[boundary_pos:]
                
                # Play the sentence
                try:
                    self.tts_stream.feed([sentence])
                    # play_async returns a coroutine, run it in executor to avoid blocking
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, self.tts_stream.play_async)
                    logger.debug(f"TTS playing: {sentence}")
                except Exception as e:
                    logger.error(f"TTS playback error: {e}")
        
        # Play any remaining text
        if buffer.strip():
            try:
                self.tts_stream.feed([buffer])
                # play_async returns a coroutine, run it in executor to avoid blocking
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self.tts_stream.play_async)
            except Exception as e:
                logger.error(f"TTS final buffer error: {e}")
    
    def _clear_tts_buffer(self):
        """Clear the TTS buffer and stop current playback."""
        self._tts_buffer = ""
        try:
            self.tts_stream.stop()
            self.tts_stream.clear_cache()
            logger.info("TTS buffer cleared")
        except Exception as e:
            logger.error(f"Error clearing TTS buffer: {e}")
    
    async def _process_transcript(self, transcript: str):
        """Process a single transcript through the LLM and TTS pipeline."""
        # Cancel any existing commentary task
        if self._current_commentary_task and not self._current_commentary_task.done():
            self._current_commentary_task.cancel()
            try:
                await self._current_commentary_task
            except asyncio.CancelledError:
                pass
            self._clear_tts_buffer()
        
        # Create new commentary task
        self._current_commentary_task = asyncio.create_task(
            self._tts_playback_stream(
                self._llm_process_stream(transcript)
            )
        )
    
    async def _transcript_consumer(self):
        """Consume transcripts from queue and process them."""
        while self._running:
            try:
                transcript = await asyncio.wait_for(
                    self._transcript_queue.get(), 
                    timeout=0.5
                )
                await self._process_transcript(transcript)
                
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Transcript consumer error: {e}")
    
    def _cleanup_audio(self):
        """Clean up audio resources."""
        if self._audio_stream:
            try:
                self._audio_stream.stop_stream()
                self._audio_stream.close()
            except Exception as e:
                logger.error(f"Error closing audio stream: {e}")
            self._audio_stream = None
        
        if self._pyaudio:
            try:
                self._pyaudio.terminate()
            except Exception as e:
                logger.error(f"Error terminating PyAudio: {e}")
            self._pyaudio = None
    
    async def start(self):
        """Start the umpire engine pipeline."""
        if self._running:
            logger.warning("UmpireEngine already running")
            return
        
        self._running = True
        logger.info("Starting UmpireEngine pipeline")
        
        # Start concurrent tasks
        tasks = [
            asyncio.create_task(self._audio_capture_loop()),
            asyncio.create_task(self._transcript_consumer())
        ]
        
        # Wait for tasks (they run until stopped)
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass
    
    async def stop(self):
        """Stop the umpire engine pipeline gracefully."""
        if not self._running:
            return
        
        logger.info("Stopping UmpireEngine pipeline")
        self._running = False
        
        # Cancel current commentary task
        if self._current_commentary_task and not self._current_commentary_task.done():
            self._current_commentary_task.cancel()
            try:
                await self._current_commentary_task
            except asyncio.CancelledError:
                pass
        
        # Clear TTS buffer
        self._clear_tts_buffer()
        
        # Cleanup audio resources
        self._cleanup_audio()
        
        logger.info("UmpireEngine pipeline stopped")
    
    def get_status(self) -> dict:
        """Get current engine status."""
        return {
            "running": self._running,
            "cuda_available": self.cuda_available,
            "device": self.device,
            "whisper_model": self.config.whisper_model_size,
            "ollama_model": self._get_ollama_model(),
            "tts_buffer_size": len(self._tts_buffer),
            "queue_size": self._transcript_queue.qsize()
        }
    
    async def process_text_input(self, text: str) -> str:
        """
        Process text input directly (for testing or manual input).
        Returns the LLM response.
        """
        try:
            model = self._get_ollama_model()
            response = ollama.chat(
                model=model,
                messages=[
                    {"role": "system", "content": self._umpire_system_prompt},
                    {"role": "user", "content": text}
                ],
                stream=False
            )
            return response['message']['content']
        except Exception as e:
            logger.error(f"Text input processing error: {e}")
            return f"Error: {str(e)}"
    
    def transcribe_audio_file(self, audio_path: str) -> str:
        """
        Transcribe an audio file using faster-whisper.
        Used for st.audio_input in Streamlit.
        
        Args:
            audio_path: Path to the audio file to transcribe
            
        Returns:
            Transcribed text from the audio
        """
        try:
            segments, _ = self.whisper_model.transcribe(
                audio_path,
                initial_prompt=TABLE_TENNIS_TERMS,
                beam_size=5
            )
            
            text = " ".join(seg.text for seg in segments).strip()
            return text
            
        except Exception as e:
            logger.error(f"Audio file transcription error: {e}")
            return ""
    
    async def _llm_process_rules_stream(
        self, 
        transcript: str, 
        rules_context: str,
        chat_history: Optional[List[Dict[str, str]]] = None
    ) -> AsyncGenerator[str, None]:
        """
        Stream LLM response for a transcript with RAG context.
        
        Args:
            transcript: The user's question
            rules_context: Retrieved rules from ChromaDB
            chat_history: Optional list of previous messages for context
            
        Yields:
            Text chunks from the LLM response
        """
        try:
            model = self._get_ollama_model()
            
            # Build messages with system prompt, context, and chat history
            messages = [
                {"role": "system", "content": self._rules_oracle_system_prompt}
            ]
            
            # Add rules context
            if rules_context:
                messages.append({
                    "role": "system", 
                    "content": f"Rule Context:\n{rules_context}"
                })
            
            # Add chat history for follow-up context
            if chat_history:
                for msg in chat_history:
                    messages.append(msg)
            
            # Add current user question
            messages.append({"role": "user", "content": transcript})
            
            # ollama.chat with stream=True returns a sync generator, run in executor
            loop = asyncio.get_event_loop()
            
            def sync_stream():
                return ollama.chat(
                    model=model,
                    messages=messages,
                    stream=True,
                    options={"num_predict": 500}  # Limit response length to prevent infinite generation
                )
            
            response_gen = await loop.run_in_executor(None, sync_stream)
            
            chunk_count = 0
            max_chunks = 200  # Safety limit to prevent infinite streaming
            for chunk in response_gen:
                chunk_count += 1
                if chunk_count > max_chunks:
                    logger.warning(f"LLM rules stream exceeded {max_chunks} chunks, stopping")
                    yield " [Response truncated due to length limit]"
                    break
                if 'message' in chunk and 'content' in chunk['message']:
                    yield chunk['message']['content']
                    
        except Exception as e:
            logger.error(f"LLM rules processing error: {e}")
            yield f"Error: {str(e)}"
    
    async def ask_rules_voice(
        self, 
        audio_path: str,
        match_context: Optional[Dict[str, Any]] = None
    ) -> AsyncGenerator[str, None]:
        """
        Process voice input for rules questions with RAG and streaming TTS.
        
        This method:
        1. Transcribes the audio file using faster-whisper
        2. Retrieves relevant rules from ChromaDB
        3. Streams the LLM response with TTS playback on sentence boundaries
        
        Args:
            audio_path: Path to the audio file to transcribe
            match_context: Optional dict with match info (player1, player2, tournament, etc.)
            
        Yields:
            Text chunks from the LLM response (for UI display)
        """
        # Step 1: Transcribe audio
        transcript = self.transcribe_audio_file(audio_path)
        
        if not transcript:
            yield "Sorry, I couldn't understand the audio."
            return
        
        logger.info(f"Voice Rules Chat - Transcribed: {transcript}")
        
        # Step 2: Retrieve relevant rules
        rules_context = self.rules_retriever.search_rules(transcript, n_results=3)
        
        # Step 3: Build match-aware context
        if match_context:
            match_info = f"Current match: {match_context.get('player1', 'Unknown')} vs {match_context.get('player2', 'Unknown')}"
            if match_context.get('tournament'):
                match_info += f" in {match_context.get('tournament')}"
            if match_context.get('score'):
                match_info += f" (Score: {match_context.get('score')})"
            
            # Enhance query with match context
            enhanced_query = f"{transcript} (Context: {match_info})"
            rules_context = self.rules_retriever.search_rules(enhanced_query, n_results=3)
        
        # Step 4: Stream LLM response with TTS on sentence boundaries
        buffer = ""
        async for text_chunk in self._llm_process_rules_stream(transcript, rules_context):
            buffer += text_chunk
            yield text_chunk
            
            # Check for sentence boundary and play TTS
            boundary_pos = self._find_sentence_boundary(buffer)
            if boundary_pos > 0:
                sentence = buffer[:boundary_pos]
                buffer = buffer[boundary_pos:]
                try:
                    self.tts_stream.feed([sentence])
                    # play_async returns a coroutine, run it in executor to avoid blocking
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, self.tts_stream.play_async)
                    logger.debug(f"TTS playing: {sentence}")
                except Exception as e:
                    logger.error(f"TTS playback error: {e}")
        
        # Play any remaining text
        if buffer.strip():
            try:
                self.tts_stream.feed([buffer])
                # play_async returns a coroutine, run it in executor to avoid blocking
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self.tts_stream.play_async)
            except Exception as e:
                logger.error(f"TTS final buffer error: {e}")
