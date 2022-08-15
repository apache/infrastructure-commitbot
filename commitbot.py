#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import asyncio
import bottom
import aiohttp
import yaml
import json
import fnmatch
import os
import asfpy.pubsub

MAX_LOG_LEN = 200

def files_touched(files):
    """Finds the root path of files touched by this commit, as well as returns a short summary of what was touched"""
    if isinstance(files, dict):  # svn returns a dict, we only care about the filenames, so convert to list
        files = list(files.keys())
    if not files:  # No files touched, likely a branch or tag was created/deleted
        return "", "No files touched"
    if len(files) == 1:  # Just one file, return that
        return files[0], files[0]
    paths = files[0].split("/")
    commit_files = 0
    commit_dirs = set()
    for file in files:
        commit_files += 1
        commit_dirs.add(os.path.dirname(file))
        while not file.startswith("/".join(paths)):
            paths.pop()
            if len(paths) == 0:
                break
    root_path = "/".join(paths)
    commit_dirs = len(commit_dirs) == 1 and "1 directory" or f"{len(commit_dirs)} directories"
    commit_files = commit_files == 1 and "1 file" or f"{commit_files} files"
    return root_path, f"{root_path} ({commit_files} in {commit_dirs})"


def format_message(payload):
    """Formats a commit payload into an IRC message"""
    commit = payload.get("commit")
    if not commit:  # Probably a still-alive ping, ignore
        return "", ""
    commit_type = commit.get("repository")
    commit_root, commit_files = files_touched(commit.get("files") or commit.get("changed", {}))
    if commit_type == "git":
        commit_subject = commit.get("subject")
        author = commit.get("email", "unknown@apache.org")
        commit_repo = commit.get("project")
        tag = commit.get("ref", "main").replace("refs/heads/", "").replace("refs/tags/", "")  # Strip refs/*/ away
        sha = commit.get("hash", "0000000")
        url = f"https://gitbox.apache.org/repos/asf?p={commit_repo}.git;h={sha}"
        return f"git:{commit_repo}", f"\x033 {author}\x03 \x02{tag} * {sha}\x0f ({commit_files}) {url}: {commit_subject}"
    else:  # if not git, then svn
        author = commit.get("committer", "unknown") + "@apache.org"
        commit_subject = commit.get("log", "No log provided")
        commit_subject = " ".join(commit_subject.split("\n"))
        if len(commit_subject) > MAX_LOG_LEN:
            commit_subject = commit_subject[:MAX_LOG_LEN-3] + "..."
        revision = commit.get("id", "1")
        url = f"https://svn.apache.org/r{revision}"
        return f"svn:{commit_root}", f"\x033 {author}\x03 \x02r{revision}\x0f ({commit_files}) {url}: {commit_subject}"


def main():
    print("Starting CommitBot")
    config = yaml.safe_load(open("config.yaml"))
    password = open(config["client"]["password"]).read().strip()
    bot = bottom.Client(
        host=config["server"]["host"], port=config["server"]["port"], ssl=config["server"].get("ssl", False)
    )

    @bot.on("CLIENT_CONNECT")
    async def connect(**kwargs):
        bot.send("NICK", nick=config["client"]["nick"])
        bot.send("USER", user=config["client"]["nick"], realname=config["client"]["realname"])

        done, pending = await asyncio.wait(
            (
                asyncio.create_task(bot.wait("RPL_ENDOFMOTD")),
                asyncio.create_task(bot.wait("ERR_NOMOTD")),
            ),
            return_when=asyncio.FIRST_COMPLETED,
        )
        for future in pending:  # Cancel whichever MOTD action never happened
            future.cancel()

        bot.send("PRIVMSG", target="NickServ", message=f"IDENTIFY {password}")
        await asyncio.sleep(10)
        for channel in config["channels"]:
            bot.send("JOIN", channel=channel)

        # Set up pubsub
        async for payload in asfpy.pubsub.listen(config["pubsub_host"]):
            root, msg = format_message(payload)
            if msg:
                sent = False
                for channel, data in config["channels"].items():
                    for tag in data.get("tags", []):
                        if fnmatch.fnmatch(root, tag):
                            bot.send("privmsg", target=channel, message=msg)
                            sent = True
                            break
                if sent:
                    await asyncio.sleep(1)  # Don't flood too quickly

    @bot.on("PING")
    def keepalive(message, **kwargs):
        bot.send("PONG", message=message)

    bot.loop.create_task(bot.connect())
    bot.loop.run_forever()


if __name__ == "__main__":
    main()
