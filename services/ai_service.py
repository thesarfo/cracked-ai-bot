import asyncio
from typing import Optional

import aiohttp
from google import genai
from google.genai import types

from config import (
  DEEPSEEK_API_KEY,
  DEEPSEEK_API_URL,
  DEEPSEEK_MODEL,
  GEMINI_API_KEY,
  GEMINI_MODEL,
)
from utils.logging import get_logger

logger = get_logger("ai")


class AIService:
  def __init__(self):
    self.use_deepseek = bool(DEEPSEEK_API_KEY)
    self.provider_name = "DeepSeek" if self.use_deepseek else "Gemini"
    self.session: Optional[aiohttp.ClientSession] = None

    if self.use_deepseek:
      self.client = None
    else:
      self.client = genai.Client(api_key=GEMINI_API_KEY).aio

    logger.info(f"🤖 AI provider: {self.provider_name}")

  async def _get_session(self) -> aiohttp.ClientSession:
    if self.session is None or self.session.closed:
      self.session = aiohttp.ClientSession()
    return self.session

  async def call_ai(
    self,
    prompt: str,
    system_message: str = "",
    context: str = "",
    use_search: bool = True,
  ) -> str:
    """Get a response from whichever AI provider is configured (DeepSeek takes
    priority over Gemini when DEEPSEEK_API_KEY is set)."""
    if not prompt:
      return "You need a prompt to be able to interact with the AI."

    full_prompt = prompt
    if context:
      full_prompt = f"{context}\n\n{prompt}"

    logger.info(f"🤖 AI request: {prompt[:80]}...")

    if self.use_deepseek:
      return await self._call_deepseek(full_prompt, system_message)
    return await self._call_gemini(full_prompt, system_message, use_search)

  async def _call_deepseek(self, prompt: str, system_message: str) -> str:
    messages = []
    if system_message:
      messages.append({"role": "system", "content": system_message})
    messages.append({"role": "user", "content": prompt})

    payload = {
      "model": DEEPSEEK_MODEL,
      "messages": messages,
      "stream": False,
    }
    headers = {
      "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
      "Content-Type": "application/json",
    }

    try:
      session = await self._get_session()
      async with session.post(DEEPSEEK_API_URL, json=payload, headers=headers) as response:
        data = await response.json()
        if response.status != 200:
          error_msg = data.get("error", {}).get("message", f"HTTP {response.status}")
          logger.error(f"DeepSeek API failed with status {response.status}: {error_msg}")
          return f"Error calling DeepSeek API: {error_msg}"

        result = data["choices"][0]["message"]["content"] or "No response from DeepSeek"
        logger.info(f"🤖 AI response: {result[:80]}...")
        return result
    except asyncio.TimeoutError:
      logger.error("AI request timed out")
      return "Error: Request timed out"
    except Exception as e:
      logger.error(f"AI error: {e}")
      return f"Error calling DeepSeek API: {str(e)}"

  async def _call_gemini(self, prompt: str, system_message: str, use_search: bool) -> str:
    try:
      # Build config with optional Google Search grounding
      tools = []
      if use_search:
        grounding_tool = types.Tool(google_search=types.GoogleSearch())
        tools.append(grounding_tool)

      config = types.GenerateContentConfig(
        tools=tools if tools else None,
        system_instruction=system_message if system_message else None,
      )

      response = await self.client.models.generate_content(
        model=GEMINI_MODEL,
        config=config,
        contents=prompt,
      )

      result = response.text if response.text else "No response from Gemini"
      logger.info(f"🤖 AI response: {result[:80]}...")
      return result
    except asyncio.TimeoutError:
      logger.error("AI request timed out")
      return "Error: Request timed out"
    except Exception as e:
      logger.error(f"AI error: {e}")
      return f"Error calling Gemini API: {str(e)}"

  async def close(self):
    if self.session and not self.session.closed:
      await self.session.close()


_ai_service: Optional[AIService] = None


def get_ai_service() -> AIService:
  global _ai_service
  if _ai_service is None:
    _ai_service = AIService()
  return _ai_service
