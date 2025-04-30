import asyncio
from fastapi import FastAPI,WebSocket,WebSocketDisconnect,HTTPException,Query
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
import requests
from fastapi.responses import HTMLResponse
from typing import List
import json
from fastapi.middleware.cors import CORSMiddleware
import os
from dotenv import load_dotenv

app = FastAPI()
load_dotenv()
# Add CORS middleware cors issue resove 
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "*"
    ],  # Replace "*" with your frontend's domain for security, e.g., ["http://localhost:3000"]
    allow_credentials=True,
    allow_methods=["*"],  # Allows all HTTP methods (GET, POST, PUT, DELETE, etc.)
    allow_headers=["*"],  # Allows all headers
)
MONGO_URI = "mongodb://localhost:27017"
client = AsyncIOMotorClient(MONGO_URI)
db = client["chat_db_new"]
users_collection = db["users"]
threads_collection = db["threads"]
messages_collection = db["messages"]

API_KEY = os.getenv("API_KEY")
ASSISTANT_ID = os.getenv("ASSISTANT_ID")
VECTOR_STORE_ID = os.getenv("VECTOR_STORE_ID")
BASE_URL = "https://api.openai.com/v1"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
    "OpenAI-Beta": "assistants=v2",
}


@app.get("/html", response_class=HTMLResponse)
async def get_html():
    with open("simplt.html", "r") as file:
        html_content = file.read()
    return HTMLResponse(content=html_content)


# Helper Functions
async def ensure_user_exists(user_id):
    """Ensure the user exists in the `users` collection."""
    existing_user = await users_collection.find_one({"user_id": user_id})
    if not existing_user:
        await users_collection.insert_one(
            {
                "user_id": user_id,
                "created_at": datetime.utcnow(),
            }
        )
        print(f"User {user_id} added to the `users` collection.")


@app.delete("/clear-chat")
async def clear_chat(user_id: str, delete_user: bool = Query(False, description="Delete user from database")):
    print(f"clear-chat: Clearing chat for user {user_id}")

    # Check if user exists
    user = await users_collection.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Concurrently delete messages and threads
    messages_result, threads_result = await asyncio.gather(
        messages_collection.delete_many({"user_id": user_id}),
        threads_collection.delete_many({"user_id": user_id}),
    )

    response = {
        "message": f"Cleared chat for user {user_id}",
        "deleted_messages": messages_result.deleted_count,
        "deleted_threads": threads_result.deleted_count,
    }

    # Optionally delete the user from the users_collection
    if delete_user:
        user_result = await users_collection.delete_one({"user_id": user_id})
        response["deleted_user"] = bool(user_result.deleted_count)

    return response

def create_thread_in_openai():
    """Create a new thread in OpenAI."""
    url = f"{BASE_URL}/threads"
    payload = {
        "tool_resources": {"file_search": {"vector_store_ids": [VECTOR_STORE_ID]}},
    }
    try:
        response = requests.post(url, headers=HEADERS, json=payload)
        response.raise_for_status()
        thread_id = response.json()["id"]
        print(f"Thread created in OpenAI with ID: {thread_id}")
        return thread_id
    except requests.exceptions.RequestException as e:
        print(f"Error creating thread in OpenAI: {e}")
        print(f"Response: {response.text}")
        raise


def send_message_to_openai(thread_id, user_message):
    """Send a message to OpenAI API."""
    print(thread_id,'theresssssssssssssssssss')
    url = f"{BASE_URL}/threads/{thread_id}/messages"
    payload = {"role": "user", "content": user_message}
    try:
        response = requests.post(url, headers=HEADERS, json=payload)
        response.raise_for_status()
        print(f"Message sent to OpenAI: {user_message}")
    except requests.exceptions.RequestException as e:
        print(f"Error sending message to OpenAI: {e}")
        print(f"Response: {response.text}")
        raise


def initiate_run_in_openai(thread_id):
    """Initiate a run in OpenAI API."""
    url = f"{BASE_URL}/threads/{thread_id}/runs"
    payload = {"assistant_id": ASSISTANT_ID}
    try:
        response = requests.post(url, headers=HEADERS, json=payload)
        response.raise_for_status()
        run_id = response.json()["id"]
        print(f"Run initiated in OpenAI with ID: {run_id}")
        return run_id
    except requests.exceptions.RequestException as e:
        print(f"Error initiating run in OpenAI: {e}")
        print(f"Response: {response.text}")
        raise


def get_run_status_in_openai(thread_id, run_id):
    """Check the status of a run in OpenAI API."""
    url = f"{BASE_URL}/threads/{thread_id}/runs/{run_id}"
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        status = response.json()["status"]
        print(f"Run status for {run_id}: {status}")
        return status
    except requests.exceptions.RequestException as e:
        print(f"Error checking run status in OpenAI: {e}")
        print(f"Response: {response.text}")
        raise


def get_thread_messages_from_openai(thread_id):
    """Retrieve thread messages from OpenAI API."""
    print("sjdhsjhdj")
    url = f"{BASE_URL}/threads/{thread_id}/messages"
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        messages = response.json()["data"]
        print(f"Retrieved messages from OpenAI for thread {thread_id}")
        return messages
    except requests.exceptions.RequestException as e:
        print(f"Error retrieving messages from OpenAI: {e}")
        print(f"Response: {response.text}")
        raise


# get all threads


@app.get("/threads", response_model=List[dict])
async def get_all_threads():
    """Retrieve all threads from the database."""
    if await threads_collection.count_documents({}) == 0:
        raise HTTPException(status_code=404, detail="No threads found")

    threads = await threads_collection.find().to_list(length=None)

    # Convert ObjectId to string for JSON serialization
    for thread in threads:
        thread["_id"] = str(thread["_id"])

    return threads


@app.get("/threads/{thread_id}/messages", response_model=List[dict])
async def get_messages(thread_id: str):
    """Retrieve messages for a given thread."""

    # Check if thread_id exists in the database
    thread = await threads_collection.find_one({"thread_id": thread_id})
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    # Fetch messages using the correct thread_id
    messages = await messages_collection.find({"thread_id": thread_id}).to_list(
        length=None
    )

    # Convert ObjectId to string for JSON serialization
    for message in messages:
        message["_id"] = str(message["_id"])

    return messages


async def process_question(thread_id, user_message):
    """Process a user question through OpenAI."""
    try:
        send_message_to_openai(thread_id, user_message)
        run_id = initiate_run_in_openai(thread_id)

        # Wait for the run to complete
        while True:
            status = get_run_status_in_openai(thread_id, run_id)
            if status == "completed":
                break
            elif status == "failed":
                raise Exception("Run failed.")
            await asyncio.sleep(2)  # Wait before checking status again

        # Retrieve assistant's response
        messages = get_thread_messages_from_openai(thread_id)
        for message in messages:
            if message["role"] == "assistant":
                # Extract 'text' value from the assistant response
                if isinstance(message["content"], list):  # If it's a list of responses
                    for item in message["content"]:
                        if item.get("type") == "text":
                            return item["text"]["value"]
                elif isinstance(message["content"], dict):  # If it's a single response
                    return message["content"].get("value", "Unknown response")
                else:
                    return "Invalid response format from assistant."
    except Exception as e:
        print(f"Error processing.... question: {e}")
        raise


@app.post("/create-chat")
async def create_chat():
    user_id = "user123"

    # Ensure unique thread_id
    while True:
        active_thread_id = create_thread_in_openai()
        existing_thread = await threads_collection.find_one(
            {"thread_id": active_thread_id}
        )

        if not existing_thread:
            break  # Exit loop when we get a unique thread_id

    # Insert the unique thread_id into the database
    await threads_collection.insert_one(
        {
            "user_id": user_id,
            "thread_id": active_thread_id,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
    )

    return active_thread_id

DEFAULT_THREAD_ID = "default-thread-id"
DEFAULT_ERROR_MESSAGE = "sorry i dont have any expertise in this as of now"

async def ensure_default_thread_exists():
    """Ensure the default thread exists in the threads collection."""
    existing_thread = await threads_collection.find_one({"thread_id": DEFAULT_THREAD_ID})
    if not existing_thread:
        await threads_collection.insert_one({
            "thread_id": DEFAULT_THREAD_ID,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        })




@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    
    """WebSocket endpoint for user communication."""
    await websocket.accept()
    # Ensure the user exists in the `users` collection
    await ensure_user_exists(user_id)
    try:
        while True:
            # Receive user message
            user_message_raw = await websocket.receive_text()
            print(f"Received message from user {user_id}")

            # Process the user's question
            try:
                user_message = json.loads(user_message_raw)  # Parse JSON
                user_message_text = user_message.get(
                    "content", "").strip()  # Extract message
                
                thread_id = user_message.get("thread_id")  # Extract thread ID
                if not thread_id:
                    error_response = json.dumps(
                        {"error": "Invalid thread", "status": 400}
                    )
                    await websocket.send_text(error_response)
                    continue
                print(
                    f"Received message from user {user_id}: {user_message_text} (Thread: {thread_id})"
                )
                #---------- continue chat  -------------
                try:
                    assistant_response = await process_question(thread_id, user_message_text)
                    if not assistant_response:
                        assistant_response = "I'm Sorry,But I don't have enough information on that. Let me know if I can help with anything else!"
                except Exception as e:
                    assistant_response = "I'm Sorry,but I don't have enough information on that. Let me know if I can help with anything else!"
                    print(f"Error in process_question: {e}")
                
                # Save user message and assistant response in `messages` collection
                timestamp = datetime.utcnow().isoformat()
                try:
                    await messages_collection.insert_one(
                        {
                            "thread_id": thread_id,
                            "user_id": user_id,
                            "sender": "user",
                            "message": user_message_text,
                            "timestamp": timestamp,
                        }
                    )
                    await messages_collection.insert_one(
                        {
                            "thread_id": thread_id,
                            "user_id": user_id,
                            "sender": "assistant",
                            "message": assistant_response,
                            "timestamp": timestamp,
                        }
                    )
                except Exception as e:
                    print(e)

                # Update the thread's `updated_at` timestamp
                await threads_collection.update_one(
                    {"thread_id": thread_id},
                    {"$set": {"updated_at": datetime.utcnow()}},
                )

                # Send the assistant's response back to the WebSocket
                # await websocket.send_text(
                #     f"thread_id: {thread_id}, message: {assistant_response}"
                # )
                # response_data = {
                #     "thread_id": thread_id,
                #         "message": assistant_response
                #             }   
                # await websocket.send_json(response_data)

                await websocket.send_text(json.dumps({"thread_id": thread_id, "message": assistant_response}))

            except Exception as e:
                error_message = f"Error processing message: {str(e)}"
                print(error_message)
                await websocket.send_text(error_message)

    except WebSocketDisconnect:
        print(f"User {user_id} disconnected.")
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
