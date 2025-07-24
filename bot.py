import os
import discord
from discord.ext import commands, tasks
import json
import asyncio
import random
import aiohttp # For making async HTTP requests to the Gemini API
from dotenv import load_dotenv # Added: Import load_dotenv

# Load environment variables from a .env file (you'll create this)
# For local development, you'd typically use `python-dotenv`.
# In a production environment (like a server), you'd set these directly.
# For this Canvas environment, we'll assume the variables are set or handle
# them as empty strings if not found, as per instructions.
load_dotenv() # Added: Load environment variables from .env

# --- Configuration ---
# Get Discord Bot Token and Gemini API Key from environment variables
# In a real environment, you'd use os.getenv('YOUR_VARIABLE_NAME')
# For this Canvas, we'll use placeholder or assume they are available.
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "") # Replace with your actual bot token or set in .env
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "") # Replace with your actual Gemini API key or set in .env

# Define the Discord bot's intents. Intents specify which events your bot wants to receive.
# Message Content intent is required to read message content.
intents = discord.Intents.default()
intents.message_content = True # Enable the message content intent

# Initialize the bot with a command prefix and intents
bot = commands.Bot(command_prefix='!', intents=intents)

# --- Global Story Storage ---
# A dictionary to store the current story for each channel.
# Key: channel_id (int), Value: current_story_text (str)
current_stories = {}

# A dictionary to store the current choices offered by the bot for each channel.
# Key: channel_id (int), Value: list of choice strings
current_choices = {}

# --- Gemini API Interaction Function ---
async def get_gemini_response(prompt: str) -> str:
    """
    Makes an asynchronous request to the Gemini API to get a creative response.
    """
    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY is not set. Cannot call Gemini API.")
        return "I need an API key to get creative! Please set GEMINI_API_KEY."

    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {'Content-Type': 'application/json'}

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}]
            }
        ]
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, headers=headers, json=payload) as response:
                response.raise_for_status() # Raise an exception for HTTP errors (4xx or 5xx)
                result = await response.json()

                if result and result.get("candidates") and result["candidates"][0].get("content") and result["candidates"][0]["content"].get("parts"):
                    return result["candidates"][0]["content"]["parts"][0]["text"]
                else:
                    print(f"Unexpected Gemini API response structure: {result}")
                    return "Hmm, I couldn't get a creative idea right now. Try again later!"
    except aiohttp.ClientError as e:
        print(f"Error calling Gemini API: {e}")
        return f"Oops! I ran into an error trying to get creative: {e}"
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return f"Something went wrong: {e}"

async def generate_and_send_choices(ctx, story_context: str):
    """
    Generates 3 story continuation choices using Gemini and sends them to the channel.
    Stores the choices for later selection.
    """
    channel_id = ctx.channel.id
    await ctx.send("The Story Weaver is thinking of the next possibilities...")

    ai_prompt = (
        f"Given the story so far: '{story_context}'. "
        "Provide three distinct continuations for the story, each 1-2 sentences long. "
        "Make them creative and varied. "
        "Format them as a numbered list (e.g., '1. ...\\n2. ...\\n3. ...')."
    )
    
    raw_choices_text = await get_gemini_response(ai_prompt)

    # Parse the raw choices text into a list of strings
    choices_list = []
    if raw_choices_text:
        # Split by newline and filter for lines starting with '1.', '2.', '3.'
        lines = raw_choices_text.split('\n')
        for i in range(1, 4): # Expecting choices 1, 2, 3
            prefix = f"{i}."
            found_choice = False
            for line in lines:
                if line.strip().startswith(prefix):
                    choices_list.append(line.strip().replace(prefix, '').strip())
                    found_choice = True
                    break
            if not found_choice:
                # If a numbered choice isn't found, try to grab any non-empty line
                # This is a fallback for less structured responses from Gemini
                for line in lines:
                    stripped_line = line.strip()
                    if stripped_line and stripped_line not in choices_list:
                        choices_list.append(stripped_line)
                        if len(choices_list) == 3: # Stop if we have 3 choices
                            break
                if len(choices_list) < 3:
                    # If still not enough choices, add placeholders or error message
                    while len(choices_list) < 3:
                        choices_list.append(f"A mysterious path unfolds (fallback {len(choices_list) + 1}).")


    if choices_list:
        current_choices[channel_id] = choices_list
        choices_message = "\n".join([f"{i+1}. {choice}" for i, choice in enumerate(choices_list)])
        await ctx.send(f"**Story so far:** {current_stories[channel_id]}\n\n**Choose your next path:**\n{choices_message}\n\nTo choose, type `!choose <number>` (e.g., `!choose 1`).")
    else:
        await ctx.send("The Story Weaver got stuck and couldn't generate choices! You can try starting a new story.")
        if channel_id in current_stories:
            del current_stories[channel_id] # Clear story if bot can't continue
        if channel_id in current_choices:
            del current_choices[channel_id] # Clear choices


# --- Bot Events ---

@bot.event
async def on_ready():
    """
    Called when the bot successfully connects to Discord.
    """
    print(f'Logged in as {bot.user.name} ({bot.user.id})')
    print('------')

@bot.event
async def on_command_error(ctx, error):
    """
    Handles errors that occur during command execution.
    """
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"Missing arguments for that command. Please check the command usage.")
    elif isinstance(error, commands.CommandNotFound):
        # Ignore if command not found, or send a subtle message if preferred
        pass
    else:
        print(f"An unexpected error occurred: {error}")
        await ctx.send(f"An unexpected error occurred: {error}")

# --- Bot Commands ---

@bot.command(name='startstory', help='Starts a new collaborative story. Usage: !startstory <your initial sentence>')
async def start_story(ctx, *, initial_sentence: str):
    """
    Starts a new story in the current channel and generates initial choices.
    """
    channel_id = ctx.channel.id
    current_stories[channel_id] = initial_sentence.strip()
    await ctx.send(f"A new story has begun! \n**Initial thought:** {current_stories[channel_id]}")
    
    # Immediately generate and send the first set of choices
    await generate_and_send_choices(ctx, current_stories[channel_id])


@bot.command(name='choose', help='Chooses a continuation for the story. Usage: !choose <number>')
async def choose_story_path(ctx, choice_number: int):
    """
    Allows the user to choose one of the presented story continuations.
    Appends the chosen part and generates new choices.
    """
    channel_id = ctx.channel.id

    if channel_id not in current_stories:
        await ctx.send("There's no story currently active in this channel! Start one with `!startstory <initial sentence>`.")
        return

    if channel_id not in current_choices or not current_choices[channel_id]:
        await ctx.send("There are no choices available right now. Please wait for the Story Weaver to provide options, or start a new story.")
        return

    if not 1 <= choice_number <= len(current_choices[channel_id]):
        await ctx.send(f"Invalid choice. Please choose a number between 1 and {len(current_choices[channel_id])}.")
        return

    # Get the chosen addition
    chosen_addition = current_choices[channel_id][choice_number - 1]
    
    # Append the chosen addition to the story
    current_stories[channel_id] += " " + chosen_addition.strip()
    
    # Clear choices for this round
    del current_choices[channel_id]

    await ctx.send(f"You chose option {choice_number}: \"{chosen_addition}\"\n")
    
    # Generate and send the next set of choices based on the updated story
    await generate_and_send_choices(ctx, current_stories[channel_id])


@bot.command(name='currentstory', help='Displays the full story so far.')
async def show_current_story(ctx):
    """
    Displays the current story in the channel.
    """
    channel_id = ctx.channel.id
    if channel_id in current_stories:
        await ctx.send(f"**Current Story:** {current_stories[channel_id]}")
    else:
        await ctx.send("There's no story currently active in this channel! Start one with `!startstory <initial sentence>`.")

# --- Run the Bot ---
# This part should be at the very end of your script.
# In a real setup, you'd put your bot token directly or load it from .env.
# For this Canvas environment, we're using the os.getenv approach.
if DISCORD_BOT_TOKEN:
    bot.run(DISCORD_BOT_TOKEN)
else:
    print("Error: DISCORD_BOT_TOKEN is not set. Please set the environment variable or replace the placeholder.")
