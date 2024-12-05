from fastapi import FastAPI
from pydantic import BaseModel, InstanceOf
from typing import Optional
from dotenv import load_dotenv
from langchain.agents import ConversationalChatAgent, AgentExecutor
from langchain.chat_models import ChatOpenAI
from langchain.memory import ConversationBufferMemory
import json
import asyncio
from sse_starlette.sse import EventSourceResponse

from tools import get_current_user_tool, get_recent_transactions_tool

load_dotenv()

app = FastAPI(title="Damn Vulnerable LLM Agent")


class ChatMessage(BaseModel):
    message: str
    conversation_id: Optional[str] = None


SYSTEM_MSG = """Assistant helps the current user retrieve the list of their recent bank transactions ans shows them as a table. Assistant will ONLY operate on the userId returned by the GetCurrentUser() tool, and REFUSE to operate on any other userId provided by the user."""

WELCOME_MESSAGE = """Hi! I'm an helpful assistant and I can help fetch information about your recent transactions.\n\nTry asking me: "What are my recent transactions?"
"""

conversations = {}


def get_memory(conversation_id: str):
    if conversation_id not in conversations:
        memory = ConversationBufferMemory(
            memory_key="chat_history", return_messages=True, output_key="output"
        )
        memory.chat_memory.add_ai_message(WELCOME_MESSAGE)
        conversations[conversation_id] = memory
    return conversations[conversation_id]


async def generate_response(message: str, conversation_id: str):
    # Use exact same tools array as Streamlit version
    tools = [get_current_user_tool, get_recent_transactions_tool]
    memory = get_memory(conversation_id)

    llm = ChatOpenAI(model_name="gpt-4o-mini", temperature=0, streaming=True)

    chat_agent = ConversationalChatAgent.from_llm_and_tools(
        llm=llm, tools=tools, verbose=True, system_message=SYSTEM_MSG
    )

    executor = AgentExecutor.from_agent_and_tools(
        agent=chat_agent,
        tools=tools,
        memory=memory,
        return_intermediate_steps=True,
        handle_parsing_errors=True,
        verbose=True,
        max_iterations=6,
    )

    async def event_generator():
        try:
            response = await asyncio.to_thread(executor, message)
            yield {
                "event": "response",
                "data": json.dumps({"output": response["output"]}),
            }

        except Exception as e:
            yield {"event": "error", "data": json.dumps({"error": str(e)})}

    return event_generator()


@app.post("/chat")
async def chat(request: ChatMessage):
    generator = await generate_response(
        request.message, request.conversation_id or "default"
    )
    return EventSourceResponse(generator)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
