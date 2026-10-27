#!/usr/bin/env python3
import os
import discord
import aiohttp
import asyncio
from dotenv import load_dotenv
from analyzer_optimized import FlashDetector
import tempfile
from urllib.parse import urlparse

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True  # Need MESSAGE_CONTENT intent

client = discord.Client(intents=intents)
detector = FlashDetector()

MAX_FILE_SIZE_MB = int(os.getenv('MAX_FILE_SIZE_MB', '10'))
MAX_DURATION_SECONDS = int(os.getenv('MAX_DURATION_SECONDS', '30'))
ACTION = os.getenv('ACTION', 'warn')

async def download_file(url: str, filename: str) -> str:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise Exception(f"Failed to download: {resp.status}")
            content = await resp.read()
            if len(content) > MAX_FILE_SIZE_MB * 1024 * 1024:
                raise Exception("File too large")
            path = os.path.join(tempfile.gettempdir(), filename)
            with open(path, 'wb') as f:
                f.write(content)
            return path

def is_media_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    # Check extensions
    if any(path.endswith(ext) for ext in ['.gif', '.mp4', '.webm', '.mov', '.avi']):
        return True
    # Check common gif hosts
    if 'giphy.com' in parsed.netloc or 'tenor.com' in parsed.netloc:
        return True
    return False

def get_extension_from_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.lower()
    for ext in ['.gif', '.mp4', '.webm', '.mov', '.avi']:
        if path.endswith(ext):
            return ext
    # Default to gif for giphy
    if 'giphy.com' in parsed.netloc:
        return '.gif'
    return '.gif'

@client.event
async def on_ready():
    print(f'Logged in as {client.user}')

@client.event
async def on_message(message):
    if message.author == client.user:
        return
    
    # Check attachments
    media_to_check = []
    
    for attachment in message.attachments:
        content_type = attachment.content_type or ''
        if content_type.startswith('image/') or content_type.startswith('video/'):
            if attachment.filename.lower().endswith(('.gif', '.mp4', '.webm', '.mov', '.avi')):
                media_to_check.append(('attachment', attachment.url, attachment.filename))
    
    # Check embeds
    for embed in message.embeds:
        if embed.thumbnail and embed.thumbnail.url:
            url = embed.thumbnail.url
            if is_media_url(url):
                media_to_check.append(('embed', url, os.path.basename(urlparse(url).path) or 'media.gif'))
        if embed.video and embed.video.url:
            url = embed.video.url
            if is_media_url(url):
                media_to_check.append(('embed', url, os.path.basename(urlparse(url).path) or 'media.mp4'))
    
    # Check URLs in content
    import re
    urls = re.findall(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', message.content)
    for url in urls:
        if is_media_url(url):
            ext = get_extension_from_url(url)
            media_to_check.append(('url', url, f'media{ext}'))
    
    if not media_to_check:
        return
    
    # Analyze each media
    for media_type, url, filename in media_to_check:
        try:
            ext = os.path.splitext(filename)[1] or get_extension_from_url(url)
            tmpfile = os.path.join(tempfile.gettempdir(), f'ep_{message.id}_{os.path.basename(filename)}')
            if not os.path.splitext(tmpfile)[1]:
                tmpfile += ext
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        continue
                    content = await resp.read()
                    if len(content) > MAX_FILE_SIZE_MB * 1024 * 1024:
                        await message.reply(f'⚠️ Media too large to scan for epilepsy triggers.')
                        continue
                    with open(tmpfile, 'wb') as f:
                        f.write(content)
            
            # Analyze
            result = detector.analyze(tmpfile)
            
            if result.get('is_triggering'):
                if ACTION == 'delete':
                    try:
                        await message.delete()
                        await message.channel.send(f'{message.author.mention} - This media may contain photosensitive epilepsy triggers and has been removed.')
                    except:
                        await message.reply(f'⚠️ **EPILEPSY WARNING:** This media may contain photosensitive epilepsy triggers! {result.get("reason")}')
                elif ACTION == 'react':
                    await message.add_reaction('⚠️')
                    await message.reply(f'⚠️ **EPILEPSY WARNING:** This media may contain photosensitive epilepsy triggers! {result.get("reason")}')
                else:  # warn
                    await message.reply(f'⚠️ **EPILEPSY WARNING:** This media may contain photosensitive epilepsy triggers! {result.get("reason")}')
            else:
                pass  # Safe, do nothing
            
            # Cleanup
            try:
                os.remove(tmpfile)
            except:
                pass
                
        except Exception as e:
            print(f"Error analyzing media: {e}")
            continue

if __name__ == '__main__':
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print("No DISCORD_TOKEN in environment")
        exit(1)
    client.run(token)


def main():
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print("No DISCORD_TOKEN in environment")
        exit(1)
    client.run(token)
